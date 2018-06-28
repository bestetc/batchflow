""" Contains two class classification metrics """
import warnings
warnings.filterwarnings("ignore")

import numpy as np

from ... import mjit
from . import Metrics, binarize, sigmoid


class ClassificationMetrics(Metrics):
    """ Metrics to assess classification models

    Parameters
    ----------
    targets : np.array
        Ground-truth labels / probabilities / logits
    predictions : np.array
        Predicted labels / probabilites / logits
    num_classes : int
        the number of classes (default is None)
    fmt : 'proba', 'logits', 'labels'
        whether arrays contain probabilities, logits or labels
    axis : int
        a class axis (default is None)
    threshold : float
        A probability level for binarization (lower values become 0, equal or greater values become 1)

    Notes
    -----
    - Input arrays (`targets` and `predictions`) might be vectors or multidimensional arrays,
    where the first dimension represents batch items. The latter is useful for pixel-level metrics.

    - When `axis` is specified, `predictions` should be a one-hot array with class information provided
    in the given axis (class probabilities or logits).

    - If `fmt` is 'labels', `num_classes` should be specified. Due to randomness any given batch may not
    contain items of some classes, so all the labels cannot be inferred as simply as `labels.max()`.

    - If `fmt` is 'proba' or 'logits', then `axis` points to the one-hot dimension.
    However, if `axis` is None, then two class classification is assumed and `targets` / `predictions`
    should contain probabilities or logits for a positive class only.


    **Metrics**
    All metrics return:

    - a single value if input is a vector for a 2-class task.
    - a single value if input is a vector for a multiclass task and multiclass averaging is enabled.
    - a vector with batch size items if input is a multidimensional array (e.g. images or sequences)
      and there are just 2 classes or multiclass averaging is on.
    - a vector with `num_classes` items if input is a vector for multiclass casse without averaging.
    - a 2d array `(batch_items, num_classes)` for multidimensional inputs in a multiclass case without averaging.

    .. note:: Count-based metrics (`true_positive`, `false_positive`, etc.) do not support mutliclass averaging.
              They always return counts for each class separately.
              For multiclass tasks rate metrics, such as `true_positive_rate`, `false_positive_rate`, etc.,
              might seem more convenient.

    **Multiclass metrics**

    In a multiclass case metrics might be calculated with or without class averaging.

    Available methods are:

    - `None` - no averaging, calculate metrics for each class individually (one-vs-all)
    - `'micro'` - calculate metrics globally by counting the total true positives,
                  false negatives, false positives, etc. across all classes
    - `'macro'` - calculate metrics for each class, and take their mean.


    Examples
    --------

    ::

        m = ClassificationMetrics(targets, predictions, num_classes=10, fmt='labels')
        m.evaluate(['sensitivity', 'specificity'], multiclass='macro')

    """
    def __init__(self, targets, predictions, fmt='proba', num_classes=None, axis=None, threshold=.5,
                 skip_bg=False, confusion=True):
        self.skip_bg = skip_bg
        self.num_classes = None if axis is None else predictions.shape[axis]
        self.num_classes = self.num_classes or num_classes or 2

        if targets.ndim == predictions.ndim:
            # targets and predictions contain the same info (labels, probabilities or logits)
            targets = self._to_labels(targets, fmt, axis, threshold)
        elif targets.ndim == predictions.ndim - 1 and fmt != 'labels':
            # targets contains labels while predictions is a one-hot array
            pass
        else:
            raise ValueError("targets and predictions should have compatible shapes",
                             targets.shape, predictions.shape)
        predictions = self._to_labels(predictions, fmt, axis, threshold)

        if targets.ndim == 1:
            targets = targets.reshape(1, -1)
            predictions = predictions.reshape(1, -1)

        self.targets = targets
        self.predictions = predictions

        self._confusion_matrix = None
        if confusion:
            self._calc_confusion()

    def _to_labels(self, arr, fmt, axis, threshold):
        if fmt == 'labels':
            pass
        elif fmt in ['proba', 'logits']:
            if axis is None:
                if fmt == 'logits':
                    arr = sigmoid(arr)
                arr = binarize(arr, threshold).astype('int8')
            else:
                arr = arr.argmax(axis=axis)
        return arr

    def one_hot(self, inputs):
        """ Convert an array of labels into a one-hot array """
        return np.eye(self.num_classes)[inputs]

    def free(self):
        """ Free memory allocated for intermediate data """
        self.targets = None
        self.predictions = None

    def _calc_confusion(self):
        self._confusion_matrix = np.zeros((self.targets.shape[0], self.num_classes, self.num_classes), dtype=np.intp)
        return self._calc_confusion_jit(self.targets, self.predictions, self.num_classes, self._confusion_matrix)

    @mjit
    def _calc_confusion_jit(self, targets, predictions, num_classes, confusion):
        for i in range(targets.shape[0]):
            targ = targets[i].flatten()
            pred = predictions[i].flatten()
            for t in range(num_classes):
                coords = np.where(targ == t)
                for c in pred[coords]:
                    confusion[i, c, t] += 1

    def _return(self, value):
        return value[0] if isinstance(value, np.ndarray) and value.shape == (1, ) else value

    def _all_labels(self):
        labels = 1 if self.skip_bg else 0
        labels = list(range(labels, self.num_classes))
        return labels

    def _count(self, f, label=None):
        if self.num_classes > 2:
            if label is None:
                return np.array([self._return(f(l)) for l in self._all_labels()]).T
        label = 1 if label is None else label
        return self._return(f(label))

    def true_positive(self, label=None, *args, **kwargs):
        _ = args, kwargs
        return self._count(lambda l: self._confusion_matrix[:, l, l], label)

    def false_positive(self, label=None, *args, **kwargs):
        _ = args, kwargs
        return self._count(lambda l: self.prediction_positive(l) - self.true_positive(l), label)

    def true_negative(self, label=None, *args, **kwargs):
        _ = args, kwargs
        return self._count(lambda l: self.condition_negative(l) - self.false_positive(l), label)

    def false_negative(self, label=None, *args, **kwargs):
        _ = args, kwargs
        return self._count(lambda l: self.condition_positive(l) - self.true_positive(l), label)

    def condition_positive(self, label=None, *args, **kwargs):
        _ = args, kwargs
        return self._count(lambda l: self._confusion_matrix[:, :, l].sum(axis=1), label)

    def condition_negative(self, label=None, *args, **kwargs):
        _ = args, kwargs
        return self._count(lambda l: self.total_population(l) - self.condition_positive(l), label)

    def prediction_positive(self, label=None, *args, **kwargs):
        _ = args, kwargs
        return self._count(lambda l: self._confusion_matrix[:, l].sum(axis=1), label)

    def prediction_negative(self, label=None, *args, **kwargs):
        _ = args, kwargs
        return self._count(lambda l: self.total_population(l) - self.prediction_positive(l), label)

    def total_population(self, *args, **kwargs):
        _ = args, kwargs
        return self._return(self._confusion_matrix.sum(axis=(1, 2)))

    def _calc_multiclass_metric(self, numer, denom, label=None, multiclass=None, when_zero=None):
        _when_zero = lambda n: np.where(n > 0, when_zero[0], when_zero[1])
        if self.num_classes > 2:
            labels = label if label is not None else self._all_labels()
            labels = labels if isinstance(labels, (list, tuple)) else [labels]
            label_value = [(numer(l, multiclass=multiclass), denom(l, multiclass=multiclass)) for l in labels]

            if multiclass is None:
                value = [np.where(l[1] > 0, l[0] / l[1], _when_zero(l[0])) for l in label_value]
                value = value[0] if len(value) == 1 else np.array(value).T
            if multiclass == 'micro':
                n = np.sum([l[0] for l in label_value], axis=0)
                d = np.sum([l[1] for l in label_value], axis=0)
                value = np.where(d > 0, n / d, _when_zero(n))
            elif multiclass in ['macro', 'mean']:
                value = np.mean([np.where(l[1] > 0, l[0] / l[1], _when_zero(l[0])) for l in label_value], axis=0)
        else:
            label = label if label is not None else 1
            d = denom(label)
            n = numer(label)
            value = np.where(d > 0, n / d, _when_zero(n))
        return value

    def true_positive_rate(self, label=None, multiclass='macro'):
        return self._calc_multiclass_metric(self.true_positive, self.condition_positive, label, multiclass,
                                            when_zero=(0, 1))

    def sensitivity(self, label=None, multiclass='macro'):
        return self.true_positive_rate(label, multiclass)

    def recall(self, label=None, multiclass='macro'):
        return self.true_positive_rate(label, multiclass)

    def false_positive_rate(self, label=None, multiclass='macro'):
        return self._calc_multiclass_metric(self.false_positive, self.condition_negative, label, multiclass,
                                            when_zero=(1, 0))

    def fallout(self, label=None, multiclass='macro'):
        return self.false_positive_rate(label, multiclass)

    def false_negative_rate(self, label=None, multiclass='macro'):
        return self._calc_multiclass_metric(self.false_negative, self.condition_positive, label, multiclass,
                                            when_zero=(1, 0))

    def miss_rate(self, label=None, multiclass='macro'):
        return self.false_negative_rate(label, multiclass)

    def true_negative_rate(self, label=None, multiclass='macro'):
        return self._calc_multiclass_metric(self.true_negative, self.condition_negative, label, multiclass,
                                            when_zero=(0, 1))

    def specificity(self, label=None, multiclass='macro'):
        return self.true_negative_rate(label, multiclass)

    def prevalence(self, label=None, multiclass='macro'):
        return self._calc_multiclass_metric(self.condition_positive, self.total_population, label, multiclass)

    def accuracy(self, *args, **kwargs):
        _ = args, kwargs
        return np.sum([self.true_positive(l) for l in self._all_labels()], axis=0) / self.total_population()

    def positive_predictive_value(self, label=None, multiclass='macro'):
        return self._calc_multiclass_metric(self.true_positive, self.prediction_positive, label, multiclass,
                                            when_zero=(0, 1))

    def precision(self, label=None, multiclass='macro'):
        return self.positive_predictive_value(label, multiclass)

    def false_discovery_rate(self, label=None, multiclass='macro'):
        return self._calc_multiclass_metric(self.false_positive, self.prediction_positive, label, multiclass,
                                            when_zero=(1, 0))

    def false_omission_rate(self, label=None, multiclass='macro'):
        return self._calc_multiclass_metric(self.false_negative, self.prediction_negative, label, multiclass,
                                            when_zero=(1, 0))

    def negative_predictive_value(self, label=None, multiclass='macro'):
        return self._calc_multiclass_metric(self.true_negative, self.prediction_negative, label, multiclass,
                                            when_zero=(0, 1))

    def positive_likelihood_ratio(self, label=None, multiclass='macro'):
        return self._calc_multiclass_metric(self.true_positive_rate, self.false_positive_rate, label, multiclass)

    def negative_likelihood_ratio(self, label=None, multiclass='macro'):
        return self._calc_multiclass_metric(self.false_negative_rate, self.true_negative_rate, label, multiclass)

    def diagnostics_odds_ratio(self, label=None, multiclass='macro'):
        return self._calc_multiclass_metric(self.positive_likelihood_ratio, self.negative_likelihood_ratio, label,
                                            multiclass)

    def f1_score(self, label=None, multiclass='macro'):
        return 2 / (1 / self.recall(label, multiclass) + 1 / self.precision(label, multiclass))
