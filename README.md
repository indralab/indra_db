[![Documentation Status](https://readthedocs.org/projects/indra-db/badge/?version=latest)](https://indra-db.readthedocs.io/en/latest/?badge=latest)

# INDRA DB

<img align="left" src="https://s3.amazonaws.com/bigmech/indra-db/indra_db_logo.png" width="480" height="200" />

The INDRA (Integrated Network and Dynamical Reasoning Assembler) Database is a
framework for creating, maintaining, and accessing a database of content,
readings, and statements. This implementation is currently designed to work
primarily with Amazon Web Services RDS running Postrgres 9+. Used as a backend
to INDRA, the INDRA Database provides a systematic way of scaling the knowledge
acquired from other databases, reading, and manual input, and puts that
knowledge at your fingertips through a direct Python client and a REST api.

### Knowledge sources

The INDRA Database currently integrates and distills knowledge from several
different sources, both biology-focused natural language processing systems and
other pre-existing databases

#### Daily Readers
We have read all available content, and every day we run the following readers:
- [REACH](https://github.com/clulab/reach)
- [Sparser](https://github.com/ddmcdonald/sparser)

we read all new content with the following readers:
- [Eidos](https://github.com/clulab/eidos)
- [ISI](https://github.com/sgarg87/big_mech_isi_gg)
- [MTI](https://ii.nlm.nih.gov/MTI/index.shtml) - used specifically to tag
content with topic terms.

we read a limited subset of new content with the following readers:
- [TRIPS](http://trips.ihmc.us/parser/cgi/drum)

on the latest content drawn from:
- [PubMed](https://www.ncbi.nlm.nih.gov/pubmed/) - ~19 million abstracts and ~29 million titles
- [PubMed Central](/www.ncbi.nlm.nih.gov/pmc/) - ~2.7 million fulltext
- [Elsevier](https://www.elsevier.com/) - ~0.7 million fulltext 
(requires special access)

#### Other Readers
We also include more or less static content extracted from the following readers:
- [RLIMS-P](https://research.bioinformatics.udel.edu/rlimsp/)

#### Other Databases
We include the information from these pre-existing databases:
- [Pathway Commons database](http://pathwaycommons.org/)
- [BEL Large Corpus](https://github.com/OpenBEL/)
- [SIGNOR](https://signor.uniroma2.it/)
- [BioGRID](https://thebiogrid.org/)
- [TAS](https://www.biorxiv.org/content/10.1101/358978v1)
- [TRRUST](https://omictools.com/trrust-tool)
- [PhosphoSitePlus](https://www.phosphosite.org/)
- [Causal Biological Networks Database](http://www.causalbionet.com/)
- [VirHostNet](http://virhostnet.prabi.fr/)
- [CTD](http://ctdbase.org/)
- [Phospho.ELM](http://phospho.elm.eu.org/)
- [DrugBank](https://www.drugbank.ca/)
- [CONIB](https://pharmacome.github.io/conib/)
- [CRoG](https://github.com/chemical-roles/chemical-roles)
- [DGI](https://www.dgidb.org/)

These databases are retrieved primarily using the tools in `indra.sources`. The
statements extracted from all of these sources are stored and updated in the
database.

### Knowledge Assembly

The INDRA Database uses the powerful internal assembly tools available in INDRA
but implemented for large-scale incremental assembly. The resulting corpus of
cleaned and de-duplicated statements, each with fully maintained provenance, is
the primary product of the database.

For more details on the internal assembly process of INDRA, see the
[INDRA documentation](http://indra.readthedocs.io/en/latest/modules/preassembler).

### Access

The content in the database can be accessed by those that created it using the
`indra_db.client` submodule. This repo also implements a REST API which can be
used by those without direct acccess to the database. For access to our REST
API, please contact the authors.

## Installation

The INDRA database only works for Python 3.6+, though some parts are still compatible with 3.5.

First, [install INDRA](http://indra.readthedocs.io/en/latest/installation.html),
then simply clone this repo, and make sure that it is visible in your
`PYTHONPATH`.

## Funding
The development of INDRA DB is funded under the DARPA Communicating with Computers program (ARO grant W911NF-15-1-0544).
