# ESBuild

> [!NOTE]
> The code in this repository has been made public as-is for informational purposes. The repository may use private resources for the building and execution of the code. For example, private registries may be used for dependency resolution.
>
> The documentation may refer to restricted URLs.

Repository for building the GDC Elasticsearch indices.

[![pre-commit](https://img.shields.io/badge/pre--commit-enabled-brightgreen?logo=pre-commit&logoColor=white)](https://github.com/pre-commit/pre-commit)

<!-- START doctoc generated TOC please keep comment here to allow auto update -->
<!-- DON'T EDIT THIS SECTION, INSTEAD RE-RUN doctoc TO UPDATE -->
**Table of Contents**  *generated with [DocToc](https://github.com/thlorenz/doctoc)*

- [Running](#running)
  - [compare_indices.py](#compare_indicespy)
    - [flags](#flags)
      - [`--test-type`](#--test-type)
      - [`--true-index` and `--test-index`](#--true-index-and---test-index)
    - [Usage](#usage)
- [Architecture](#architecture)
  - [Build and Upload Process](#build-and-upload-process)
  - [Builders and Mappers](#builders-and-mappers)
    - [Mappers](#mappers)
- [Trouble shooting](#trouble-shooting)
- [Installation](#installation)
  - [Pip](#pip)
    - [Project Dependencies](#project-dependencies)
- [Development](#development)
  - [Tests](#tests)
  - [Setup pre-commit hook to check for secrets](#setup-pre-commit-hook-to-check-for-secrets)
- [Production](#production)
- [Contributing](#contributing)

<!-- END doctoc generated TOC please keep comment here to allow auto update -->

# Running

## compare_indices.py

This is a script used to compare 2 indices. It can be used to see the changes between
new indices and old indices. An output file with name `counts_<index_name>_vs_<another_index_name>.json`
or `compared_<index_name>_vs_<another_index_name>.json` will be generated.

### flags

#### `--test-type`

Choose between `compare-counts` and `full-compare`

* `compare-counts` will show the count difference for indices.
* `full-compare` will show detailed doc difference for indices.

#### `--true-index` and `--test-index`

The base names of the two elasticsearch indices being tested. All
gdc_from_graph (annotation, case, file, project) subtypes will be tested.


### Usage

```bash
compare_indices.py --true-index dr33_active_merged --test_index dr33_active_merged_v2 --test-type compare_counts
```


=========
# Architecture

## Build and Upload Process

The JSON index is built in the following steps:

0. Cache the graph from the database in memory
0. Filter out nodes from the graph that should be excluded
0. Cache commonly used information, e.g. case to file relationships
0. Visit each case, producing a case doc and all annotation and file docs for that case
0. Merge file docs together (to allow for multiple cases in a file doc)
0. Produce project summary docs
0. Validate produced docs

The index is uploaded to elasticsearch in the following steps:

0. Create a new index in naming scheme
0. Upload each doc type to index
0. On success, update the alias to point to new index
0. Cleanup/close old indexes

## Builders and Mappers

Esbuild consists of a `builder` and a `mapper` for the four indices it produces: project,
annotation, file, and case.

* The `mapper` produces the Elasticsearch mapping and contains basic traversals
* The `builder` produces JSON documents using the `mapper`

Most of the business logic for building indices is contained in the
`graph.common.builder.GraphIndexBuilder` class, which is inherited by
`graph.common.builder.ActiveGraphIndexBuilder` to implement the actual
build of the indices.

Builders exclude nodes that shouldn't be in the index (and therefore
public) based during the filtering step in the `is_node_indexed()`
function.

Each builder has a set of class variables that alter build behavior,
including but not limited to `mapper`, `file_mapping`,
`case_to_file_paths`, `unindexed_by_property`, `hidden_properties`.
Those that are required to be overloaded are listed in
`required_attrs`.

Each `case` document contains all of the files derived from it.  Each
`file` document in that case document contain a _pruned_ version of
the parent `case` document that contains only the direct ancestors of
the file, i.e. only those found along all paths from the file to the
case.  This re-nesting is done to allow additional filtering in
Elasticsearch.

Because file documents are produced by visiting a single case, the
traversal from that case to each file will only contain one case.
This means that file documents must be merged together in order to
contain all the cases they are derived from. This is done as follows:

0. for each file doc from `denormalize_case() -> (case_docs,
   file_docs, annotation_docs)`
0. if there is an existing doc for this file and the newly produced
   document contains a subtree for a case that is not in the old doc,
   then append the case subtree from the new doc to that of the old
   doc.

### Mappers

The mappers (see the `graph.common.mappings` module) produce the
_mapping_ (or schema) for Elasticsearch.  The common mappers is futher
extended in the active mapper which is used to produce the main mappings
for the indices which will be built in the builder.

The mappers have three main functions to produce mappings:
`get_{project,case,annotation,file}_es_mapping`.

The properties of each Entity (Node class) are dynamically added to
the mapping based on the GDC Dictionary.

The traversal tree in the active mappings is dynamic and based on
the graph structure.

# Trouble shooting

The active module contains a ActiveMimic builder which can be used
to test functionality against nodes, e.g. testing `builder.is_node_indexed(node)`
to troubleshoot nodes that are not showing up in the index.

```python
>>> from esbuild.graph.active.mimic import ActiveMimic
>>> from gdcdatamodel.models import Case
>>> mimic = ActiveMimic(None)
>>> mimic.is_node_indexed(Case())
[...][graph_index][   INFO] not indexed (unsubmitted state: <Case(None)>): None
False
```

# Installation

Before continuing you must have the following programs installed:

- [Python 3.13](http://python.org/)

## Pip

Project dependencies are managed using
[PIP](https://pip.readthedocs.org/en/latest/). You can install
dependencies via

```bash
pip install -r requirements.txt
```

And optionally any dev requirements via

```bash
pip install '.[dev]'
```

### Project Dependencies

If you are building to a local Elasticsearch installation, you will
need to install it manually.  On OSX you can install Elasticsearch via
`brew install elasticsearch`.

# Development

## Tests

Use [tox](https://tox.readthedocs.io/en/latest/) to run tests:

```
pip install tox
tox
```

The test suite data is visualized in a PDF
using [graphviz](http://www.graphviz.org/) if you have installed
whenever the tests are run.

### Parallel testing

We are now able to run the tests in parallel, with `indexd_test_utils2`,
`pytest-postgresql`, `pytest-elasticsearch` and `pytest-xdist`.
To start test in parallel, run with the following command:
```bash
USE_RUNNING_ES=false USE_RUNNING_PG=false pytest tests -n auto
```

You have to export postgres path so `pg_config` is available for `pytest-postgresql`.

If your elasticsearch is not installed in default location or your are using opensearch,
set the following env:
```bash
ES_EXECUTABLE=/opt/homebrew/opt/opensearch/bin/opensearch
```

If you are using mac, you also need to set:
```bash
OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
```

## Setup pre-commit hook to check for secrets

We use [pre-commit](https://pre-commit.com/) to setup pre-commit hooks for this repo.
We use [detect-secrets](https://github.com/Yelp/detect-secrets) to search for secrets being committed into the repo.

To install the pre-commit hook, run
```bash
pre-commit install
```

To update the .secrets.baseline file run
```bash
detect-secrets scan --update .secrets.baseline
```

`.secrets.baseline` contains all the string that were caught by detect-secrets but are not stored in plain text. Audit the baseline to view the secrets .

```bash
detect-secrets audit .secrets.baseline
```

# Production

This library was written with the intention of deploying via SaltStack
and
[tungsten](https://github.com/NCI-GDC/tungsten/tree/develop/tungsten).

# Contributing

Read how to
contribute
[here](https://github.com/NCI-GDC/esbuild/blob/develop/CONTRIBUTING.md).


## Opt-in project file metadata ownership

Set `PROJECT_VISIBILITY_ENABLED=true` only for a complete build into fresh index
names. The default is false and retains existing builder behavior. The feature
uses authenticated IndexD lookup results already cached by the builder to attach
canonical `_gen3_file_authz` ownership to root and embedded files. Graph `file_id`
and IndexD `object_id` can differ; their ownership comes from the same trusted
lookup, not the case's graph project. Mixed public cases retain their clinical
metadata while file children receive independent ownership. The builder also
prepares contribution groups for safe case/project file counts.

Legacy graph summaries count file nodes, while the file index merges graph nodes
that share an IndexD `object_id`. Opted-in graph builds verify each case's complete
embedded file list against its file-index GUID memberships, check project case
coverage and file memberships, then reconcile counts/sizes to unique GUIDs before
ownership preparation. A graph-node count difference alone is not evidence of an
incomplete export. Missing GUIDs and inconsistent relationships still fail before
index creation, with the affected scope and membership differences in the error.
The launcher logs caching, denormalization and ownership-preparation durations,
in addition to its total successful runtime.

Preparation validates all ownership and summaries before any index is changed.
An opted-in build may select projects, but must rebuild their complete served
projection into fresh indices. Versioned builds and existing destination indices
are rejected before cleanup. It cannot incrementally update an old index. Use a new
prefix and review/switch served aliases through the normal operator process.
Existing object mappings cannot become nested in place. Fresh mappings preserve
field definitions while adding ownership fields, making owned embedded objects
nested and removing their parent copies. Build output adds no policy grants.

Query services must support the matching contract. Changing user visibility
later requires only usersync; ingestion or a change in file ownership requires a
fresh projection build. Other genomic builders need the offline preparation step
in the GitOps runbook; this repository builds the graph-derived case/file/project
and annotation projections only. Keep private files out of other stores until
those stores enforce the same ownership.

Run isolated transformation/mapping tests without the graph model stack:
`PYTHONPATH=src python -m unittest discover -s tests -p test_project_file_visibility.py -v`.
Full graph build/integration acceptance remains required before dev rollout.

Opted-in default builders require `INDEXD_USERNAME` and `INDEXD_PASSWORD` from
server secrets. The prior anonymous client cannot export complete ownership once
IndexD enforcement is enabled. The builder pins the MMRF client revision that
forwards Basic credentials on GET, using its existing standard IndexD interface.
Default opt-out builders retain their anonymous authentication tuple. Test the
full graph build with this pinned client before rollout.

The normal `run.sh` / `single.py` launcher retains its existing project list
whether visibility is enabled or disabled. Ownership must cover every file in
that selected projection, not unrelated graph projects. Selective graph caching
remains enabled. It writes fresh prefixed indices with `roll_alias=False`; alias
promotion remains an operator action. Opted-in builds skip destination cleanup
and claim each index atomically, so concurrent builds cannot reuse another job's
destination.

After the normal file-ID normalization, export mutation inputs from the existing
local physical indices with:

```bash
export PROJECT_VISIBILITY_ENABLED=true
python -u src/esbuild/bin/export_visibility_inputs.py "$VIS_PREFIX" \
  --stage "$VIS_STAGE" \
  --mutation-repo "$HOME/mmrf-mutation-indexer" \
  --indexd-base-url "https://dev-virtuallab.themmrf.org/index"
```

This reads the complete case/file/project/annotation sources, validates their file
memberships and prepared ownership, and selects authenticated IndexD records
referenced anywhere in those sources, including nonstandard reference fields and
prefixed GUID aliases. Unreferenced legacy records do not need ownership cleanup
to export this build. Referenced unowned or missing GUIDs still stop preparation;
no `/open` or other policy is invented. Current ownership must match the prepared
indices. Only after validation does it publish private, non-overwriting
`indexd-manifest.json`, `files.ndjson` and `config-visibility.toml` in the stage
directory. The override contains credentials and points to the rebuilt mutation
driver, new physical input/output indices and stage-local logs. It retains normal
resource/connection settings when supplied last to the mutation client.
This exporter does not rebuild search indices or change aliases. Existing indices
from the graph-summary compatibility revision remain valid input.
