[![Run Status](https://api.shippable.com/projects/58c6ada92e042a0600297f61/badge?branch=master)](https://app.shippable.com/github/analysiscenter/dataset)

# Dataset

`Dataset` helps you conveniently work with random or sequential batches of your data
and define data processing and machine learning workflows even for datasets that do not fit into memory.

For more details see [the documentation and tutorials](https://analysiscenter.github.io/dataset/).

Main features:
- flexible batch generaton
- deterministic and stochastic pipelines
- datasets and pipelines joins and merges
- data processing actions
- flexible model configuration
- within batch parallelism
- batch prefetching
- ready to use ML models and proven NN architectures
- convenient layers and helper functions to build custom models.

## Basic usage

```python
my_workflow = my_dataset.pipeline()
              .load('/some/path')
              .do_something()
              .do_something_else()
              .some_additional_action()
              .save('/to/other/path')
```
The trick here is that all the processing actions are lazy. They are not executed until their results are needed, e.g. when you request a preprocessed batch:
```python
my_workflow.run(BATCH_SIZE, shuffle=True, n_epochs=5)
```
or
```python
for batch in my_workflow.gen_batch(BATCH_SIZE, shuffle=True, n_epochs=5):
    # only now the actions are fired and data is being changed with the workflow defined earlier
    # actions are executed one by one and here you get a fully processed batch
```
or
```python
NUM_ITERS = 1000
for i in range(NUM_ITERS):
    processed_batch = my_workflow.next_batch(BATCH_SIZE, shuffle=True, n_epochs=None)
    # only now the actions are fired and data is changed with the workflow defined earlier
    # actions are executed one by one and here you get a fully processed batch
```

For more advanced cases and detailed API see [the documentation](https://analysiscenter.github.io/dataset/).


## Installation

> `Dataset` module is in the beta stage. Your suggestions and improvements are very welcome.

> `Dataset` supports python 3.5 or higher.

### Python package
With modern [pipenv](https://docs.pipenv.org/)
```
pipenv install git+https://github.com/analysiscenter/dataset.git#egg=dataset
```

With old-fashioned [pip](https://pip.pypa.io/en/stable/)
```
pip3 install git+https://github.com/analysiscenter/dataset.git
```

After that just import `dataset`:
```python
import dataset as ds
```

### Git submodule
In many cases it might be more convenient to install `dataset` as a submodule in your project repository than as a python package.
```
git submodule add https://github.com/analysiscenter/dataset.git
git submodule init
git submodule update
```

If your python file is located in another directory, you might need to add a path to `dataset`:
```python
import sys
sys.path.insert(0, "/path/to/dataset")
import dataset as ds
```

What is great about using a submodule that every commit in your project can be linked to its own commit of a submodule.
This is extremely convenient in a fast paced research environment.

Local import is also possible:
```python
from .dataset.dataset import Dataset
```

It requires a double dataset in the import line, though.


## Citing Dataset
Please cite Dataset in your publications if it helps your research.

[![DOI](https://zenodo.org/badge/84835419.svg)](https://zenodo.org/badge/latestdoi/84835419)

```
Roman Kh et al. Dataset library for fast ML workflows. 2017. doi:10.5281/zenodo.1041203
```

```
@misc{roman_kh_2017_1041203,
  author       = {Roman Kh and et al},
  title        = {Dataset library for fast ML workflows},
  year         = 2017,
  doi          = {10.5281/zenodo.1041203},
  url          = {https://doi.org/10.5281/zenodo.1041203}
}
```
