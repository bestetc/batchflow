import os
import sys
import re
import dill
import glob
import json
import logging
import subprocess
import contextlib
from collections import OrderedDict

from .profiler import ExperimentProfiler
from .results import ResearchResults
from .utils import to_list, create_logger, jsonify, create_output_stream

class ExperimentStorage:
    def __init__(self, experiment, loglevel=None):
        self.experiment = experiment
        self.loglevel = loglevel or 'error'
        self.results = None

        self.create_profiler()

    def update_variable(self, name, value): #iteration is availiable from experiment
        results = self.results.get(name, OrderedDict())
        results[self.experiment.iteration] = value
        self.results[name] = results #TODO: do we need it?

    def create_profiler(self):
        profile = self.experiment.profile
        if profile == 2 or isinstance(profile, str) and 'detailed'.startswith(profile):
            self._profiler = ExperimentProfiler(detailed=True)
        elif profile == 1 or profile is True:
            self._profiler = ExperimentProfiler(detailed=False)
        else: # 0, False, None
            self._profiler = None

    def close(self):
        experiment = self.experiment
        if experiment.research is not None:
            experiment.research.storage.results.put(experiment.id, experiment.results, experiment.config_alias)
            if self._profiler is not None:
                experiment.research.profiler.put(experiment.id, self._profiler.profile_info)

        self.dump_results()
        self.dump_profile()
        self.close_files()
        self.close_logger()

    def dump_results(self, variable=None):
        pass

    def dump_profile(self):
        pass

    def close_files(self):
        """ Close stdout/stderr files (if rederection was performed. """
        if not isinstance(self.stdout_file, (contextlib.nullcontext, type(None))):
            self.stdout_file.close()
        if not isinstance(self.stderr_file, (contextlib.nullcontext, type(None))):
            self.stderr_file.close()

    def close_logger(self):
        """ Close experiment logger. """
        self.logger.removeHandler(self.logger.handlers[0])

class MemoryExperimentStorage(ExperimentStorage):
    def __init__(self, experiment, loglevel=None):
        super().__init__(experiment, loglevel)

        self.results = OrderedDict()

        self.create_logger()
        self.create_streams()

    def create_logger(self):
        research = self.experiment.research
        name = os.path.join(research.name, self.experiment.name) if research else self.experiment.name
        self.logger = create_logger(name, None, self.loglevel)

    def create_streams(self):
        self.stdout_file = create_output_stream(self.experiment.redirect_stdout, False, common=False)
        self.stderr_file = create_output_stream(self.experiment.redirect_stderr, False, common=False)

class LocalExperimentStorage(ExperimentStorage):
    def __init__(self, experiment, loglevel=None):
        super().__init__(experiment, loglevel)

        self.loglevel = loglevel or 'info'

        self.create_folder()
        self.dump_config()
        self.create_logger()
        self.create_empty_results()

    def create_folder(self):
        """ Create folder for experiment results. """
        self.experiment_path = os.path.join('experiments', self.experiment.id)
        self.full_path = os.path.join(self.experiment.name, self.experiment_path)
        if not os.path.exists(self.full_path):
            os.makedirs(self.full_path)
        else:
            raise ValueError(f'Experiment folder {self.full_path} already exists.')

    def dump_config(self):
        """ Dump config (as serialized ConfigAlias instance). """
        with open(os.path.join(self.full_path, 'config.dill'), 'wb') as file:
            dill.dump(self.experiment.config_alias, file)
        with open(os.path.join(self.full_path, 'config.json'), 'w') as file:
            json.dump(jsonify(self.experiment.config.config), file)

    def create_logger(self, loglevel=None):
        loglevel = loglevel or self.loglevel
        if self.experiment.research:
            name = self.experiment.research.name
        else:
            name = self.experiment.executor.name
        logger_name = os.path.join(name, self.experiment.id)
        path = os.path.join(name, 'experiments', self.experiment.id, 'experiment.log')
        self.logger = create_logger(logger_name, path, loglevel)

    def create_empty_results(self):
        # if self.experiment.research is not None:
        #     results = self.experiment.research.results.results
        #     results[self.experiment.id] = OrderedDict()
        #     self.results = results[self.experiment.id]
        # else:
        #     self.results = OrderedDict()
        self.results = OrderedDict()

    def create_streams(self):
        self.stdout_file = create_output_stream(
            self.experiment.redirect_stdout, True, 'stdout.txt', path=self.full_path, common=False
        )
        self.stderr_file = create_output_stream(
            self.experiment.redirect_stderr, True, 'stderr.txt', path=self.full_path, common=False
        )

    def dump_results(self, variable=None):
        """ Callable to dump results. """
        variables_to_dump = list(self.results.keys()) if variable is None else to_list(variable)
        for var in variables_to_dump:
            values = self.results[var]
            iteration = self.experiment.iteration
            variable_path = os.path.join(self.full_path, 'results', var)
            if not os.path.exists(variable_path):
                os.makedirs(variable_path)
            filename = os.path.join(variable_path, str(iteration))
            with open(filename, 'wb') as file:
                dill.dump(values, file)
            del self.results[var]

    def dump_profile(self):
        if self._profiler is not None:
            path = os.path.join(self.full_path, 'profiler.feather')
            self._profiler.profile_info.reset_index().to_feather(path)

class ResearchStorage:
    def __init__(self, research=None, loglevel=None):
        self.research = research
        self.loglevel = loglevel or 'error'

        self.results = None

    def collect_env_state(self, env_meta_to_collect):
        for item in env_meta_to_collect:
            args = item.pop('args', [])
            kwargs = item.pop('kwargs', {})
            self._collect_env_state(*args, **item, **kwargs)

    def _collect_env_state(self, cwd='.', dst=None, replace=None, commands=None, *args, **kwargs):
        """ Execute commands and save output. """
        if cwd == '.' and dst is None:
            dst = 'cwd'
        elif dst is None:
            dst = os.path.split(os.path.realpath(cwd))[1]

        if isinstance(commands, (tuple, list)):
            args = [*commands, *args]
        elif isinstance(commands, dict):
            kwargs = {**commands, **kwargs}

        all_commands = [('env_state', command) for command in args]
        all_commands = [*all_commands, *kwargs.items()]

        for filename, command in all_commands:
            if command.startswith('#'):
                if command[1:] == 'python':
                    result = sys.version
                else:
                    raise ValueError(f'Unknown env: {command}')
            else:
                process = subprocess.Popen(command.split(), stdout=subprocess.PIPE, cwd=cwd)
                output, _ = process.communicate()
                result = output.decode('utf')
            if replace is not None:
                for key, value in replace.items():
                    result = re.sub(key, value, result)

            self.store_env(result, dst, filename)

    def create_logger(self):
        name = self.research.name
        path = os.path.join(name, 'research.log')
        self.logger = create_logger(name, path, self.loglevel)

    def close_files(self):
        """ Close stdout/stderr files (if rederection was performed. """
        if not isinstance(self.stdout_file, (contextlib.nullcontext, type(None))):
            self.stdout_file.close()
        if not isinstance(self.stderr_file, (contextlib.nullcontext, type(None))):
            self.stderr_file.close()

    def close(self):
        self.results.close_manager()

class MemoryResearchStorage(ResearchStorage):
    def __init__(self, research=None, loglevel=None):
        super().__init__(research)
        self.loglevel = loglevel or 'error'

        self.create_logger()
        self.results = ResearchResults(self.research.name, False)

        self._env = dict()

    def create_logger(self):
        self.logger = create_logger(self.research.name, None, self.loglevel)

    def store_env(self, result, dst, filename):
        key = os.path.join(dst, filename)
        self._env[key] = self._env.get(key, '') + result

    @property
    def env(self):
        return self._env

    def create_streams(self):
        self.stdout_file = create_output_stream(self.research.redirect_stdout, False, common=True)
        self.stderr_file = create_output_stream(self.research.redirect_stderr, False, common=True)

class LocalResearchStorage(ResearchStorage):
    def __init__(self, research, loglevel, mode='w'):
        super().__init__(research)

        self.loglevel = loglevel or 'info'
        self.path = research.name
        if mode == 'w':
            self.create_folder()
        self.dump_research(research)
        self.create_logger()
        self.results = ResearchResults(self.research.name, True)

    def create_folder(self):
        """ Create storage folder. """
        if os.path.exists(self.path):
            raise ValueError(f"Research storage '{self.path}' already exists")
        os.makedirs(self.path)
        for subfolder in ['env', 'experiments']:
            path = os.path.join(self.path, subfolder)
            if not os.path.exists(path):
                os.makedirs(path)

    def dump_research(self, research):
        with open(os.path.join(self.path, 'research.dill'), 'wb') as f:
            dill.dump(research, f)
        with open(os.path.join(self.path, 'research.txt'), 'w') as f:
            f.write(str(research))

    def create_logger(self):
        path = os.path.join(self.research.name, 'research.log')
        self.logger = create_logger(self.research.name, path, self.loglevel)

    def store_env(self, result, dst, filename):
        subfolder = os.path.join(self.path, 'env', dst)
        if not os.path.exists(subfolder):
            os.makedirs()
        with open(os.path.join(subfolder, filename + '.txt'), 'a') as file:
            file.write(result)

    @property
    def env(self):
        """ Environment state. """
        env = dict()
        filenames = glob.glob(os.path.join(self.path, 'env', '*'))
        for filename in filenames:
            name = os.path.splitext(os.path.basename(filename))[0]
            with open(filename, 'r') as file:
                env[name] = file.read().strip()
        return env

    def create_streams(self):
        self.stdout_file = create_output_stream(
            self.research.redirect_stdout, True, 'stdout.txt', self.research.name, common=True
        )
        self.stderr_file = create_output_stream(
            self.research.redirect_stderr, True, 'stderr.txt', self.research.name, common=True
        )

class ClearMLResearchStorage(ResearchStorage):
    def __init__(self, research, path):
        super().__init__(research)
