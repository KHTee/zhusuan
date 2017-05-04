#!/usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import absolute_import
from __future__ import print_function
from __future__ import division
from collections import OrderedDict

import six
from six.moves import zip
import tensorflow as tf

from zhusuan.model.utils import Context, TensorArithmeticMixin


__all__ = [
    'StochasticTensor',
    'BayesianNet',
    'reuse',
]


class StochasticTensor(TensorArithmeticMixin):
    """
    The :class:`StochasticTensor` class is an abstraction built upon
    :class:`~zhusuan.distributions.base.Distribution`. It's the base class for
    various stochastic nodes used when building Bayesian Networks (Directed
    graphical models).

    For all distributions available in :mod:`zhusuan.distributions` there is a
    corresponding `StochasticTensor`, which can be accessed by
    ``zhusuan.Normal`` (for example, a univariate Normal `StochasticTensor`).
    Their instances are Tensor-like, which enables transparent building of
    Bayesian Networks using tensorflow primitives. See :class:`BayesianNet`
    for examples of usage.

    .. seealso::

        :doc:`/concepts`

    :param name: A string. The name of the `StochasticTensor`. Must be unique
        in the `BayesianNet` context.
    :param distribution: A :class:`~zhusuan.distributions.base.Distribution`
        instance that determines the distribution used in this stochastic node.
    :param n_samples: A 0-D `int32` Tensor. Number of samples generated by
        this `StochasticTensor`.
    :param observed: A Tensor, which matches the shape of `distribution`.
        If specified, will be used as the value of this stochastic tensor,
        instead of sampling from the distribution.  This argument will 
        also overwrite the value provided via BayesianNet context.
    """

    def __init__(self, name, distribution, n_samples, observed=None):
        self._name = name
        self._distribution = distribution
        self._n_samples = n_samples
        self._dtype = distribution.dtype
        if observed is not None:
            try:
                observed = tf.convert_to_tensor(observed, dtype=self.dtype)
            except ValueError as e:
                raise ValueError(
                    "StochasticTensor('{}') not compatible "
                    "with its observed value. Error message: {}".format(
                        self._name, e))
        self._observed = observed
        try:
            self._net = BayesianNet.get_context()
            self._net._add_stochastic_tensor(self)
        except RuntimeError:
            self._net = None

    @property
    def name(self):
        """The name of the `StochasticTensor`."""
        return self._name

    @property
    def distribution(self):
        """The distribution used in this `StochasticTensor`."""
        return self._distribution

    @property
    def dtype(self):
        """Tensor type of the samples."""
        return self._dtype

    @property
    def net(self):
        """The BayesianNet context where this `StochasticTensor` is in."""
        return self._net

    @property
    def tensor(self):
        """
        Return corresponding Tensor through sampling, or if observed, return
        the observed value.

        :return: A Tensor.
        """
        if not hasattr(self, '_tensor'):
            if self._observed is not None:
                self._tensor = self._observed
            elif self._name in self._net.observed:
                try:
                    self._tensor = tf.convert_to_tensor(
                        self._net.observed[self._name], dtype=self._dtype)
                except ValueError as e:
                    raise ValueError(
                        "StochasticTensor('{}') not compatible "
                        "with its observed value. Error message: {}".format(
                            self._name, e))
            else:
                self._tensor = self.sample(self._n_samples)
        return self._tensor

    def sample(self, n_samples):
        """
        Return samples from this `StochasticTensor`.

        :return: A Tensor.
        """
        return self._distribution.sample(n_samples)

    def log_prob(self, given):
        """
        Compute log probability density (mass) function at `given` value.

        :param given: A Tensor. The value at which to evaluate log probability
            density (mass) function.
        :return: A Tensor. The log probability density (mass) value.
        """
        return self._distribution.log_prob(given)

    def prob(self, given):
        """
        Compute probability density (mass) function at `given` value.

        :param given: A Tensor. The value at which to evaluate probability
            density (mass) function.
        :return: A Tensor. The probability density (mass) value.
        """
        return self._distribution.prob(given)

    def __hash__(self):
        # Necessary to support Python's collection membership operators
        return id(self)

    def __eq__(self, other):
        # Necessary to support Python's collection membership operators
        return id(self) == id(other)

    # disallowed operators
    def __iter__(self):
        raise TypeError("StochasticTensor object is not iterable.")

    def __bool__(self):
        raise TypeError(
            "Using a `StochasticTensor` as a Python `bool` is not allowed. "
            "Use `if t is not None:` instead of `if t:` to test if a "
            "tensor is defined, and use TensorFlow ops such as "
            "tf.cond to execute subgraphs conditioned on the value of "
            "a tensor."
        )

    def __nonzero__(self):
        raise TypeError(
            "Using a `StochasticTensor` as a Python `bool` is not allowed. "
            "Use `if t is not None:` instead of `if t:` to test if a "
            "tensor is defined, and use TensorFlow ops such as "
            "tf.cond to execute subgraphs conditioned on the value of "
            "a tensor."
        )

    @staticmethod
    def _to_tensor(value, dtype=None, name=None, as_ref=False):
        if dtype and not dtype.is_compatible_with(value.dtype):
            raise ValueError("Incompatible type conversion requested to type "
                             "'{}' for variable of type '{}'".
                             format(dtype.name, value.dtype.name))
        if as_ref:
            raise ValueError("{}: Ref type not supported.".format(value))
        return value.tensor


tf.register_tensor_conversion_function(
    StochasticTensor, StochasticTensor._to_tensor)


class BayesianNet(Context):
    """
    The :class:`BayesianNet` class is a context class supporting model
    construction in ZhuSuan as Bayesian Networks (Directed graphical models).
    A `BayesianNet` represents a DAG with two kinds of nodes:

    * Deterministic nodes, made up of any tensorflow operations.
    * Stochastic nodes, constructed by :class:`StochasticTensor`.

    To start a :class:`BayesianNet` context::

        import zhusuan as zs
        with zs.BayesianNet() as model:
            # build the model

    A Bayesian Linear Regression example:

    .. math::

        w \\sim N(0, \\alpha^2 I)

        y \\sim N(w^Tx, \\beta^2)

    ::

        import tensorflow as tf
        import zhusuan as zs

        def bayesian_linear_regression(x, alpha, beta):
            with zs.BayesianNet() as model:
                w = zs.Normal('w', mean=0., logstd=tf.log(alpha)
                y_mean = tf.reduce_sum(tf.expand_dims(w, 0) * x, 1)
                y = zs.Normal('y', y_mean, tf.log(beta))
            return model

    To observe any stochastic nodes in the network, pass a dictionary mapping
    of ``(name, Tensor)`` pairs when constructing :class:`BayesianNet`.
    This will assign observed values to corresponding
    :class:`StochasticTensor` s. For example::

        def bayesian_linear_regression(observed, x, alpha, beta):
            with zs.BayesianNet(observed=observed) as model:
                w = zs.Normal('w', mean=0., logstd=tf.log(alpha)
                y_mean = tf.reduce_sum(tf.expand_dims(w, 0) * x, 1)
                y = zs.Normal('y', y_mean, tf.log(beta))
            return model

        model = bayesian_linear_regression({'w': w_obs}, ...)

    will set ``w`` to be observed. The result is that ``y_mean`` is computed
    from the observed value of ``w`` (``w_obs``) instead of the samples of
    ``w``. Calling the above function with different `observed` arguments
    instantiates :class:`BayesianNet` with different observations, which
    is a common behaviour for probabilistic graphical models.

    .. note::

        The observation passed must have the same type and shape as the
        `StochasticTensor`.

    After construction, :class:`BayesianNet` supports queries on the network::

        # get samples of random variable y following generative process
        # in the network
        model.outputs('y')

        # because w is observed in this case, its observed value will be
        # returned
        model.outputs('w')

        # get local log probability values of w and y, which returns
        # log p(w) and log p(y|w, x)
        model.local_log_prob(['w', 'y'])

        # query many quantities at the same time
        model.query('w', outputs=True, local_log_prob=True)

    .. seealso::

        :doc:`/concepts`

    :param observed: A dictionary of (string, Tensor) pairs, which maps from
        names of random variables to their observed values.
    """

    def __init__(self, observed=None):
        self.observed = observed if observed else {}
        self._stochastic_tensors = OrderedDict()

    def _add_stochastic_tensor(self, s_tensor):
        """
        Add a `StochasticTensor` to the network. This is the function called
        when a `StochasticTensor` is created in the `BayesianNet` context.

        :param s_tensor: A :class:`StochasticTensor` instance.
        """
        if s_tensor.name in self._stochastic_tensors:
            raise ValueError("There has been a StochasticTensor with name "
                             "'{}' in the network. Names should be unique".
                             format(s_tensor.name))
        else:
            self._stochastic_tensors[s_tensor.name] = s_tensor

    def outputs(self, name_or_names):
        """
        Get the outputs of :class:`StochasticTensor` s by their names,
        following generative process in the network. For observed variables,
        their observed values are returned; while for latent variables,
        samples are returned.

        :param name_or_names: A string or a list of strings. Names of
            `StochasticTensor` s in the network.
        :return: A Tensor or a list of Tensors.
        """
        if isinstance(name_or_names, (tuple, list)):
            return [self._stochastic_tensors[name].tensor
                    for name in name_or_names]
        else:
            return self._stochastic_tensors[name_or_names].tensor

    def local_log_prob(self, name_or_names):
        """
        Get local probability density (mass) values of
        :class:`StochasticTensor` s by their names. For observed variables,
        the probability is evaluated at their observed values; for latent
        variables, the probability is evaluated at their sampled values.

        :param name_or_names: A string or a list of strings. Names of
            `StochasticTensor` s in the network.
        :return: A Tensor or a list of Tensors.
        """
        if isinstance(name_or_names, (tuple, list)):
            ret = []
            for name in name_or_names:
                s_tensor = self._stochastic_tensors[name]
                ret.append(s_tensor.log_prob(s_tensor.tensor))
        else:
            s_tensor = self._stochastic_tensors[name_or_names]
            ret = s_tensor.log_prob(s_tensor.tensor)
        return ret

    def query(self, name_or_names, outputs=False, local_log_prob=False):
        """
        Make probabilistic queries on the `BayesianNet`. Various options
        are available:

        * outputs: See :meth:`outputs`.
        * local_log_prob: See :meth:`local_log_prob`.

        For each queried :class:`StochasticTensor`, a tuple containing results
        of selected options is returned. If only one is queried, the returned
        is a tuple; else the returned is a list of tuples.

        :param name_or_names: A string or a list of strings. Names of
            `StochasticTensor` s in the network.
        :param outputs: A bool. Whether to query outputs.
        :param local_log_prob: A bool. Whether to query local log probability
            density (mass) values.

        :return: Tuple of Tensors or a list of tuples of Tensors.
        """
        ret = []
        if outputs:
            ret.append(self.outputs(name_or_names))
        if local_log_prob:
            ret.append(self.local_log_prob(name_or_names))
        if len(ret) == 0:
            raise ValueError("No query options are selected.")
        elif isinstance(name_or_names, (tuple, list)):
            return list(zip(*ret))
        else:
            return tuple(ret)

    def log_joint(self):
        """
        Built-in log joint probability function for this Bayesian Network,
        which automatically sums over all local log probabilities in the
        network.

        .. warning::

            This function may do things wrong when the network has data
            sub-sampling.
        """
        return tf.add_n(
            self.local_log_prob(list(six.iterkeys(self._stochastic_tensors))),
            name='log_joint')


def reuse(scope):
    """
    A decorator for transparent reuse of tensorflow
    `Variables <https://www.tensorflow.org/api_docs/python/tf/Variable>`_ in a
    function. The decorated function will automatically create variables the
    first time they are called and reuse them thereafter.

    .. note::

        This decorator is internally implemented by tensorflow's 
        :func:`make_template` function. See `its doc
        <https://www.tensorflow.org/api_docs/python/tf/make_template>_`
        for requirements on the target function.

    :param scope: A string. The scope name passed to tensorflow
        `variable_scope()
        <https://www.tensorflow.org/api_docs/python/tf/variable_scope>`_.
    """
    return lambda f: tf.make_template(scope, f)
