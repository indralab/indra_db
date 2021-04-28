__all__ = ['TasManager', 'CBNManager', 'HPRDManager', 'SignorManager',
           'BiogridManager', 'BelLcManager', 'PathwayCommonsManager',
           'RlimspManager', 'TrrustManager', 'PhosphositeManager',
           'CTDManager', 'VirHostNetManager', 'PhosphoElmManager',
           'DrugBankManager']

import os
import zlib
import boto3
import pickle
import logging
import tempfile
from collections import defaultdict
from indra.statements.validate import assert_valid_statement
from indra_db.util import insert_db_stmts
from indra_db.util.distill_statements import extract_duplicates, KeyFunc

logger = logging.getLogger(__name__)


class KnowledgebaseManager(object):
    """This is a class to lay out the methods for updating a dataset."""
    name = NotImplemented
    short_name = NotImplemented
    source = NotImplemented

    def upload(self, db):
        """Upload the content for this dataset into the database."""
        dbid = self._check_reference(db)
        stmts = self._get_statements()
        # Raise any validity issues with statements as exceptions here
        # to avoid uploading invalid content.
        for stmt in stmts:
            assert_valid_statement(stmt)
        insert_db_stmts(db, stmts, dbid)
        return

    def update(self, db):
        """Add any new statements that may have come into the dataset."""
        dbid = self._check_reference(db, can_create=False)
        if dbid is None:
            raise ValueError("This knowledge base has not yet been "
                             "registered.")
        existing_keys = set(db.select_all([db.RawStatements.mk_hash,
                                           db.RawStatements.source_hash],
                                          db.RawStatements.db_info_id == dbid))
        stmts = self._get_statements()
        filtered_stmts = [s for s in stmts
                          if (s.get_hash(), s.evidence[0].get_source_hash())
                          not in existing_keys]
        insert_db_stmts(db, filtered_stmts, dbid)
        return

    def _check_reference(self, db, can_create=True):
        """Ensure that this database has an entry in the database."""
        dbinfo = db.select_one(db.DBInfo, db.DBInfo.db_name == self.short_name)
        if dbinfo is None:
            if can_create:
                dbid = db.insert(db.DBInfo, db_name=self.short_name,
                                 source_api=self.source, db_full_name=self.name)
            else:
                return None
        else:
            dbid = dbinfo.id
            if dbinfo.source_api != self.source:
                dbinfo.source_api = self.source
                db.commit("Could not update source_api for %s."
                          % dbinfo.db_name)
        return dbid

    def _get_statements(self):
        raise NotImplementedError("Statement retrieval must be defined in "
                                  "each child.")


class TasManager(KnowledgebaseManager):
    """This manager handles retrieval and processing of the TAS dataset."""
    name = 'TAS'
    short_name = 'tas'
    source = 'tas'

    def _get_statements(self):
        from indra.sources import tas
        # The settings we use here are justified as follows:
        # - only affinities that indicate binding are included
        # - only agents that have some kind of a name available are
        #   included, with ones that get just an ID as a name are
        #   not included.
        # - we do not require full standardization, thereby allowing
        #   set of drugs to be extracted for which we have a name from CHEBML,
        #   HMS-LINCS, or DrugBank
        logger.info('Processing TAS from web')
        tp = tas.process_from_web(affinity_class_limit=2,
                                  named_only=True,
                                  standardized_only=False)
        logger.info('Expanding evidences and deduplicating')
        filtered_stmts = [s for s in _expanded(tp.statements)]
        unique_stmts, _ = extract_duplicates(filtered_stmts,
                                             KeyFunc.mk_and_one_ev_src)
        return unique_stmts


class SignorManager(KnowledgebaseManager):
    name = 'Signor'
    short_name = 'signor'
    source = 'signor'

    def _get_statements(self):
        from indra.sources.signor import process_from_web
        proc = process_from_web()
        return proc.statements


class CBNManager(KnowledgebaseManager):
    """This manager handles retrieval and processing of CBN network files"""
    name = 'Causal Bionet'
    short_name = 'cbn'
    source = 'bel'

    def __init__(self, archive_url=None):
        if not archive_url:
            self.archive_url = ('http://www.causalbionet.com/Content'
                                '/jgf_bulk_files/Human-2.0.zip')
        else:
            self.archive_url = archive_url
        return

    def _get_statements(self):
        import requests
        from zipfile import ZipFile
        from indra.sources.bel.api import process_cbn_jgif_file
        import tempfile

        cbn_dir = tempfile.mkdtemp('cbn_manager')

        logger.info('Retrieving CBN network zip archive')
        tmp_zip = os.path.join(cbn_dir, 'cbn_human.zip')
        resp = requests.get(self.archive_url)
        with open(tmp_zip, 'wb') as f:
            f.write(resp.content)

        stmts = []
        tmp_dir = os.path.join(cbn_dir, 'cbn')
        os.mkdir(tmp_dir)
        with ZipFile(tmp_zip) as zipf:
            logger.info('Extracting archive to %s' % tmp_dir)
            zipf.extractall(path=tmp_dir)
            logger.info('Processing jgif files')
            for jgif in zipf.namelist():
                if jgif.endswith('.jgf') or jgif.endswith('.jgif'):
                    logger.info('Processing %s' % jgif)
                    pbp = process_cbn_jgif_file(os.path.join(tmp_dir, jgif))
                    stmts += pbp.statements

        uniques, dups = extract_duplicates(stmts,
                                           key_func=KeyFunc.mk_and_one_ev_src)

        logger.info("Deduplicating...")
        print('\n'.join(str(dup) for dup in dups))
        print(len(dups))

        return uniques


class BiogridManager(KnowledgebaseManager):
    name = 'BioGRID'
    short_name = 'biogrid'
    source = 'biogrid'

    def _get_statements(self):
        from indra.sources import biogrid
        bp = biogrid.BiogridProcessor()
        return list(_expanded(bp.statements))


class PathwayCommonsManager(KnowledgebaseManager):
    name = 'Pathway Commons'
    short_name = 'pc'
    source = 'biopax'
    skips = {'psp', 'hprd', 'biogrid', 'phosphosite', 'phosphositeplus',
             'ctd', 'drugbank'}

    def __init__(self, *args, **kwargs):
        self.counts = defaultdict(lambda: 0)
        super(PathwayCommonsManager, self).__init__(*args, **kwargs)

    def _can_include(self, stmt):
        num_ev = len(stmt.evidence)
        assert num_ev == 1, "Found statement with %d evidence." % num_ev

        ev = stmt.evidence[0]
        ssid = ev.annotations['source_sub_id']
        self.counts[ssid] += 1

        return ssid not in self.skips

    def _get_statements(self):
        s3 = boto3.client('s3')

        logger.info('Loading PC content pickle from S3')
        resp = s3.get_object(Bucket='bigmech',
                             Key='indra-db/biopax_pc12_pybiopax.pkl')
        logger.info('Loading PC statements from pickle')
        stmts = pickle.loads(resp['Body'].read())

        logger.info('Expanding evidences and deduplicating')
        filtered_stmts = [s for s in _expanded(stmts) if self._can_include(s)]
        unique_stmts, _ = extract_duplicates(filtered_stmts,
                                             KeyFunc.mk_and_one_ev_src)
        return unique_stmts


class CTDManager(KnowledgebaseManager):
    name = 'CTD'
    source = 'ctd'
    short_name = 'ctd'
    subsets = ['gene_disease', 'chemical_disease',
               'chemical_gene']

    def _get_statements(self):
        s3 = boto3.client('s3')
        all_stmts = []
        for subset in self.subsets:
            logger.info('Fetching CTD subset %s from S3...' % subset)
            key = 'indra-db/ctd_%s.pkl' % subset
            resp = s3.get_object(Bucket='bigmech', Key=key)
            stmts = pickle.loads(resp['Body'].read())
            all_stmts += [s for s in _expanded(stmts)]
        # Return exactly one of multiple statements that are exactly the same
        # in terms of content and evidence.
        unique_stmts, _ = extract_duplicates(all_stmts,
                                             KeyFunc.mk_and_one_ev_src)
        return unique_stmts


class DrugBankManager(KnowledgebaseManager):
    name = 'DrugBank'
    short_name = 'drugbank'
    source = 'drugbank'

    def _get_statements(self):
        s3 = boto3.client('s3')
        logger.info('Fetching DrugBank statements from S3...')
        key = 'indra-db/drugbank_5.1.pkl'
        resp = s3.get_object(Bucket='bigmech', Key=key)
        stmts = pickle.loads(resp['Body'].read())
        expanded_stmts = [s for s in _expanded(stmts)]
        # Return exactly one of multiple statements that are exactly the same
        # in terms of content and evidence.
        unique_stmts, _ = extract_duplicates(expanded_stmts,
                                             KeyFunc.mk_and_one_ev_src)
        return unique_stmts


class VirHostNetManager(KnowledgebaseManager):
    name = 'VirHostNet'
    short_name = 'vhn'
    source = 'virhostnet'

    def _get_statements(self):
        from indra.sources import virhostnet
        vp = virhostnet.process_from_web()
        return [s for s in _expanded(vp.statements)]


class PhosphoElmManager(KnowledgebaseManager):
    name = 'Phospho.ELM'
    short_name = 'pe'
    source = 'phosphoelm'

    def _get_statements(self):
        from indra.sources import phosphoelm
        logger.info('Fetching PhosphoElm dump from S3...')
        s3 = boto3.resource('s3')
        tmp_dir = tempfile.mkdtemp('phosphoelm_files')
        dump_file = os.path.join(tmp_dir, 'phosphoelm.dump')
        s3.meta.client.download_file('bigmech',
                                     'indra-db/phosphoELM_all_2015-04.dump',
                                     dump_file)
        logger.info('Processing PhosphoElm dump...')
        pp = phosphoelm.process_from_dump(dump_file)
        logger.info('Expanding evidences on PhosphoElm statements...')
        # Expand evidences just in case, though this processor always
        # produces a single evidence per statement.
        stmts = [s for s in _expanded(pp.statements)]
        # Return exactly one of multiple statements that are exactly the same
        # in terms of content and evidence.
        # Now make sure we don't include exact duplicates
        unique_stmts, _ = extract_duplicates(stmts, KeyFunc.mk_and_one_ev_src)
        return unique_stmts


class HPRDManager(KnowledgebaseManager):
    name = 'HPRD'
    short_name = 'hprd'
    source = 'hprd'

    def _get_statements(self):
        import tarfile
        import requests
        from indra.sources import hprd

        # Download the files.
        hprd_base = 'http://www.hprd.org/RELEASE9/'
        resp = requests.get(hprd_base + 'HPRD_FLAT_FILES_041310.tar.gz')
        tmp_dir = tempfile.mkdtemp('hprd_files')
        tmp_tarfile = os.path.join(tmp_dir, 'hprd_files.tar.gz')
        with open(tmp_tarfile, 'wb') as f:
            f.write(resp.content)

        # Extract the files.
        with tarfile.open(tmp_tarfile, 'r:gz') as tf:
            tf.extractall(tmp_dir)

        # Find the relevant files.
        dirs = os.listdir(tmp_dir)
        for files_dir in dirs:
            if files_dir.startswith('FLAT_FILES'):
                break
        files_path = os.path.join(tmp_dir, files_dir)
        file_names = {'id_mappings_file': 'HPRD_ID_MAPPINGS',
                      'complexes_file': 'PROTEIN_COMPLEXES',
                      'ptm_file': 'POST_TRANSLATIONAL_MODIFICATIONS',
                      'ppi_file': 'BINARY_PROTEIN_PROTEIN_INTERACTIONS',
                      'seq_file': 'PROTEIN_SEQUENCES'}
        kwargs = {kw: os.path.join(files_path, fname + '.txt')
                  for kw, fname in file_names.items()}

        # Run the processor
        hp = hprd.process_flat_files(**kwargs)

        # Filter out exact duplicates
        unique_stmts, dups = \
            extract_duplicates(_expanded(hp.statements),
                               key_func=KeyFunc.mk_and_one_ev_src)
        print('\n'.join(str(dup) for dup in dups))

        return unique_stmts


class BelLcManager(KnowledgebaseManager):
    name = 'BEL Large Corpus'
    short_name = 'bel_lc'
    source = 'bel'

    def _get_statements(self):
        from indra.sources import bel

        pbp = bel.process_large_corpus()
        stmts = pbp.statements
        pbp = bel.process_small_corpus()
        stmts += pbp.statements
        stmts, dups = extract_duplicates(stmts,
                                         key_func=KeyFunc.mk_and_one_ev_src)
        print('\n'.join(str(dup) for dup in dups))
        print(len(stmts), len(dups))
        return stmts


class PhosphositeManager(KnowledgebaseManager):
    name = 'Phosphosite Plus'
    short_name = 'psp'
    source = 'biopax'

    def _get_statements(self):
        from indra.sources import biopax

        s3 = boto3.client('s3')
        resp = s3.get_object(Bucket='bigmech',
                             Key='indra-db/Kinase_substrates.owl.gz')
        owl_gz = resp['Body'].read()
        owl_str = \
            zlib.decompress(owl_gz, zlib.MAX_WBITS + 32).decode('utf-8')
        bp = biopax.process_owl_str(owl_str)
        stmts, dups = extract_duplicates(bp.statements,
                                         key_func=KeyFunc.mk_and_one_ev_src)
        print('\n'.join(str(dup) for dup in dups))
        print(len(stmts), len(dups))
        return stmts


class RlimspManager(KnowledgebaseManager):
    name = 'RLIMS-P'
    short_name = 'rlimsp'
    source = 'rlimsp'
    _rlimsp_root = 'https://hershey.dbi.udel.edu/textmining/export/'
    _rlimsp_files = [('rlims.medline.json', 'pmid'),
                     ('rlims.pmc.json', 'pmcid')]

    def _get_statements(self):
        from indra.sources import rlimsp
        import requests

        stmts = []
        for fname, id_type in self._rlimsp_files:
            print("Processing %s..." % fname)
            res = requests.get(self._rlimsp_root + fname)
            jsonish_str = res.content.decode('utf-8')
            rp = rlimsp.process_from_jsonish_str(jsonish_str, id_type)
            stmts += rp.statements
            print("Added %d more statements from %s..."
                  % (len(rp.statements), fname))

        stmts, dups = extract_duplicates(_expanded(stmts),
                                         key_func=KeyFunc.mk_and_one_ev_src)
        print('\n'.join(str(dup) for dup in dups))
        print(len(stmts), len(dups))

        return stmts


class TrrustManager(KnowledgebaseManager):
    name = 'TRRUST'
    short_name = 'trrust'
    source = 'trrust'

    def _get_statements(self):
        from indra.sources import trrust
        tp = trrust.process_from_web()
        unique_stmts, dups = \
            extract_duplicates(_expanded(tp.statements),
                               key_func=KeyFunc.mk_and_one_ev_src)
        print(len(dups))
        return unique_stmts


def _expanded(stmts):
    for stmt in stmts:
        # Only one evidence is allowed for each statement.
        if len(stmt.evidence) > 1:
            for ev in stmt.evidence:
                new_stmt = stmt.make_generic_copy()
                new_stmt.evidence.append(ev)
                yield new_stmt
        else:
            yield stmt


class DgiManager(KnowledgebaseManager):
    """This manager handles retrieval and processing of the DGI dataset."""
    name = 'DGI'
    short_name = 'dgi'
    source = 'dgi'

    def _get_statements(self):
        from indra.sources import dgi
        logger.info('Processing DGI from web')
        dp = dgi.process_version('2020-Nov')
        logger.info('Expanding evidences and deduplicating')
        filtered_stmts = [s for s in _expanded(dp.statements)]
        unique_stmts, _ = extract_duplicates(filtered_stmts,
                                             KeyFunc.mk_and_one_ev_src)
        return unique_stmts


class CrogManager(KnowledgebaseManager):
    """This manager handles retrieval and processing of the CRoG dataset."""
    name = 'CRoG'
    short_name = 'crog'
    source = 'crog'

    def _get_statements(self):
        from indra.sources import crog
        logger.info('Processing CRoG from web')
        cp = crog.process_from_web()
        logger.info('Expanding evidences and deduplicating')
        filtered_stmts = [s for s in _expanded(cp.statements)]
        unique_stmts, _ = extract_duplicates(filtered_stmts,
                                             KeyFunc.mk_and_one_ev_src)
        return unique_stmts


class ConibManager(KnowledgebaseManager):
    """This manager handles retrieval and processing of the CONIB dataset."""
    name = 'CONIB'
    short_name = 'conib'
    source = 'conib'

    def _get_statements(self):
        import pybel
        import requests
        from indra.sources.bel import process_pybel_graph
        logger.info('Processing CONIB from web')
        url = 'https://github.com/pharmacome/conib/raw/master/conib' \
            '/_cache.bel.nodelink.json'
        res_json = requests.get(url).json()
        graph = pybel.from_nodelink(res_json)
        # Get INDRA statements
        pbp = process_pybel_graph(graph)

        # Fix and issue with PMID spaces
        for stmt in pbp.statements:
            for ev in stmt.evidence:
                if ev.pmid:
                    ev.pmid = ev.pmid.strip()
                if ev.text_refs.get('PMID'):
                    ev.text_refs['PMID'] = ev.text_refs['PMID'].strip()

        logger.info('Expanding evidences and deduplicating')
        filtered_stmts = [s for s in _expanded(pbp.statements)]
        unique_stmts, _ = extract_duplicates(filtered_stmts,
                                             KeyFunc.mk_and_one_ev_src)
        return unique_stmts


if __name__ == '__main__':
    import sys
    from indra_db.util import get_db
    mode = sys.argv[1]
    db = get_db('primary')
    for Manager in KnowledgebaseManager.__subclasses__():
        kbm = Manager()
        print(kbm.name, '...')
        if mode == 'upload':
            kbm.upload(db)
        elif mode == 'update':
            kbm.update(db)
        else:
            print("Invalid mode: %s" % mode)
            sys.exit(1)
