#pylint:disable=broad-except
#pylint:disable=attribute-defined-outside-init

""" Classes Job and Experiment. """

from collections import OrderedDict

from .. import inbatch_parallel

class Job:
    """ Contains one job. """
    def __init__(self, executable_units, n_iters, repetition, configs, branches, name):
        """
        Parameters
        ----------
        config : dict or Config
            config of experiment
        """
        self.experiments = []
        # self.config = config

        self.executable_units = executable_units
        self.n_iters = n_iters
        self.configs = configs
        self.repetition = repetition
        self.branches = branches
        self.name = name


    def init(self, worker_config, gpu_configs):
        """ Create experiments. """
        self.worker_config = worker_config

        for unit in self.executable_units.values():
            unit.exec_for = self.get_iterations(unit.exec_for, self.n_iters)
            unit.dump_for = self.get_iterations(unit.dump_for, self.n_iters)

        for index, config in enumerate(self.configs):
            if isinstance(self.branches, list):
                branch_config = self.branches[index]
            else:
                branch_config = dict()
            units = OrderedDict()
            for name, unit in self.executable_units.items():
                unit = unit.get_copy()
                if unit.pipeline is not None:
                    import_config = {key: units[value].pipeline for key, value in unit.kwargs.items()}
                else:
                    import_config = dict()
                unit.set_config(config, {**branch_config, **gpu_configs[index]}, worker_config, import_config)
                unit.repetition = self.repetition[index]
                unit.index = index
                unit.create_folder(self.name)
                units[name] = unit

            self.experiments.append(units)

    def get_iterations(self, execute_for, n_iters=None):
        """ Get indices of iterations from execute_for. """
        if n_iters is not None:
            if isinstance(execute_for, int):
                if execute_for == -1:
                    execute_for = [n_iters - 1]
                else:
                    execute_for = list(range(-1, n_iters, execute_for))
            elif execute_for is None:
                execute_for = list(range(n_iters))
        return execute_for

    def get_description(self):
        """ Get description of job. """
        if isinstance(self.branches, list):
            description = '\n'.join([str({**config.alias(), **_config, **self.worker_config})
                                     for config, _config in zip(self.configs, self.branches)])
        else:
            description = '\n'.join([str({**config.alias(), **self.worker_config})
                                     for config in self.configs])
        return description

    def parallel_execute_for(self, iteration, name, run=False):
        """ Parallel execution of pipeline 'name'. """
        if run:
            while True:
                try:
                    batch = self.executable_units[name].next_batch_root()
                    self._parallel_run(iteration, name, batch)
                except Exception:
                    break
        else:
            batch = self.executable_units[name].next_batch_root()
            self._parallel_run(iteration, name, batch)
        self.put_all_results(iteration, name)


    @inbatch_parallel(init='_parallel_init_run')
    def _parallel_run(self, item, iteration, name, batch):
        _ = name
        item.execute_for(batch, iteration)

    def _parallel_init_run(self, iteration, name, batch):
        _ = iteration, batch
        return [experiment[name] for experiment in self.experiments]

    @inbatch_parallel(init='_parallel_init_call')
    def parallel_call(self, item, iteration, name):
        item[name](iteration, item, *item[name].args, **item[name].kwargs)

    def _parallel_init_call(self, iteration, name):
        _ = iteration, name
        return [[experiment] for experiment in self.experiments]

    def put_all_results(self, iteration, name, result=None):
        """ Add values of pipeline variables to results. """
        for experiment in self.experiments:
            experiment[name].put_result(iteration, result)
