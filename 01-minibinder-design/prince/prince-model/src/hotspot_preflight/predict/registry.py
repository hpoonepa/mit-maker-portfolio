# SPDX-License-Identifier: MIT
"""Which site predictors are available, and how to get one by name.

This exists because the predictor is meant to be swapped. Site ranking is
published prior art (see :mod:`.base`); our contribution is the downstream
assembly-aware filter, and the claim we can actually support is the improvement
that filter makes *to a given backend*. Measuring that means being able to run
the same pipeline over several backends, which means naming them.

Third-party backends register themselves through the
``hotspot_preflight.predictors`` entry-point group, so a wrapper around a
published predictor can live in its own package under its own licence. That
separation is deliberate and not merely tidy: DiscoTope-3.0 is CC BY-NC-4.0 and
SEMA's licence file is unrelated boilerplate, so neither can be vendored into
this MIT repository.

**The registry is a class, not a module-level dict.** The obvious design — a
module global that :func:`register` mutates — makes the test suite
order-dependent: a backend registered by one test is still registered for the
next, a fake entry point injected by one file leaks into another, and the
resulting failure shows up only when the full suite runs in a different order
than it did locally. :class:`PredictorRegistry` can be instantiated, so a test
gets its own and mutates nothing shared. :data:`DEFAULT_REGISTRY` is the one
process-wide instance the module-level functions delegate to, which keeps the
convenient ``registry.get("geometric")`` call for real callers.
"""

from __future__ import annotations

import warnings
from importlib import metadata
from typing import Any, Callable, Iterable, Mapping, Protocol

from .base import SitePredictor
from .external import ExternalPredictor
from .geometric import GeometricPredictor

__all__ = [
    "ENTRY_POINT_GROUP",
    "UnknownPredictorError",
    "PredictorPluginWarning",
    "PredictorRegistry",
    "DEFAULT_REGISTRY",
    "register",
    "available",
    "get",
    "refresh",
    "snapshot",
    "restore",
]

ENTRY_POINT_GROUP = "hotspot_preflight.predictors"

PredictorFactory = Callable[..., SitePredictor]


class _EntryPointLike(Protocol):
    """What the registry needs of an entry point, so a test can supply a stub."""

    name: str
    value: str

    def load(self) -> PredictorFactory: ...


class UnknownPredictorError(LookupError):
    """No predictor is registered under that name."""


class PredictorPluginWarning(UserWarning):
    """A third-party predictor plugin could not be loaded, or was shadowed."""


def _external_factory(path: str, name: str = "external") -> ExternalPredictor:
    """Adapter so ``get("external", path=...)`` works with a no-arg factory API.

    :class:`ExternalPredictor` takes ``(name, path)`` in that order, which is
    the natural call for a human writing it out but awkward for a registry whose
    other factories need no arguments at all.
    """
    return ExternalPredictor(name, path)


_external_factory.name = "external"  # type: ignore[attr-defined]

BUILTIN_FACTORIES: tuple[PredictorFactory, ...] = (
    GeometricPredictor,
    _external_factory,
)


def _factory_name(factory: PredictorFactory) -> str:
    candidate = getattr(factory, "name", None)
    if isinstance(candidate, str) and candidate:
        return candidate
    raise ValueError(
        f"cannot infer a predictor name from {factory!r}: it has no string "
        f"'name' attribute. Pass name= explicitly."
    )


def _installed_entry_points() -> list[_EntryPointLike]:
    """Entry points of :data:`ENTRY_POINT_GROUP` actually installed here."""
    return list(metadata.entry_points(group=ENTRY_POINT_GROUP))


class PredictorRegistry:
    """A named collection of predictor factories.

    Args:
        entry_points: zero-argument callable returning the entry points to
            discover. Injected rather than monkeypatched so a test can supply
            fakes without reaching into :mod:`importlib.metadata` or into this
            module's globals — which is what made the old module-level design
            order-dependent.
        builtins: register :data:`BUILTIN_FACTORIES` immediately. The built-ins
            are eager because a tool that cannot offer its own baseline until
            something asks twice is just confusing.
    """

    def __init__(
        self,
        *,
        entry_points: Callable[[], Iterable[_EntryPointLike]] | None = None,
        builtins: bool = True,
    ) -> None:
        self._factories: dict[str, PredictorFactory] = {}
        self._scanned = False
        self._entry_points = entry_points or _installed_entry_points
        if builtins:
            for factory in BUILTIN_FACTORIES:
                self.register(factory)

    def __repr__(self) -> str:
        return f"PredictorRegistry({sorted(self._factories)})"

    def register(
        self,
        factory: PredictorFactory,
        name: str | None = None,
        *,
        replace: bool = False,
    ) -> str:
        """Make ``factory`` available under ``name``, returning the name used.

        Args:
            factory: a callable returning a :class:`~.base.SitePredictor`.
                Called lazily by :meth:`get`, so a backend that needs to load a
                model or open a file costs nothing until it is asked for.
            name: the registry name. Defaults to ``factory.name`` — a dataclass
                field default or class attribute is enough.
            replace: permit overwriting an existing registration.

        Raises:
            ValueError: on a duplicate name without ``replace``. Silent
                shadowing would let an installed plugin take over the name
                ``"geometric"`` and change what a published run means without
                anything in the run record saying so.
        """
        resolved = name if name is not None else _factory_name(factory)
        if not resolved:
            raise ValueError("a predictor name must not be empty")
        if resolved in self._factories and not replace:
            raise ValueError(
                f"a predictor named {resolved!r} is already registered; "
                f"pass replace=True if that is intended"
            )
        self._factories[resolved] = factory
        return resolved

    def _scan(self) -> None:
        """Load third-party backends once, surviving a broken plugin.

        A plugin that fails to import must not take the whole tool down — the
        built-in baseline still works, and the user needs to be told which
        plugin is broken rather than handed its import traceback in place of
        their run.
        """
        if self._scanned:
            return
        self._scanned = True
        for entry in self._entry_points():
            if entry.name in self._factories:
                warnings.warn(
                    f"ignoring plugin {entry.value!r}: the name "
                    f"{entry.name!r} is already registered, and letting a "
                    f"plugin shadow it would change what that name means "
                    f"without saying so.",
                    PredictorPluginWarning,
                    stacklevel=2,
                )
                continue
            try:
                factory = entry.load()
            except Exception as exc:  # noqa: BLE001 - reported, not swallowed
                warnings.warn(
                    f"predictor plugin {entry.name!r} ({entry.value}) failed "
                    f"to load: {exc!r}. It will not be available.",
                    PredictorPluginWarning,
                    stacklevel=2,
                )
                continue
            self._factories[entry.name] = factory

    def refresh(self) -> None:
        """Re-scan the entry-point group.

        Needed because the scan is cached: a plugin installed, or a fake
        injected by a test, after the first :meth:`available` call would
        otherwise never be seen.
        """
        self._scanned = False
        self._scan()

    def available(self) -> list[str]:
        """Registered predictor names, sorted."""
        self._scan()
        return sorted(self._factories)

    def get(self, name: str, /, **kwargs: Any) -> SitePredictor:
        """Build the predictor registered under ``name``.

        ``kwargs`` go to the factory, which is how a backend that needs an
        argument is reached — ``get("external", path="scores.csv")``.

        ``name`` is positional-only so that a factory may itself take a ``name``
        argument without colliding with this one: ``get("external", path=p,
        name="discotope3")`` reaches :class:`ExternalPredictor`, whose whole job
        is to be labelled with the tool that produced the file.

        Raises:
            UnknownPredictorError: naming every available predictor, because
                the useful response to a typo is the list of real options, not
                a KeyError holding the typo.
        """
        self._scan()
        try:
            factory = self._factories[name]
        except KeyError:
            raise UnknownPredictorError(
                f"no predictor named {name!r}; available: "
                f"{sorted(self._factories)}"
            ) from None
        return factory(**kwargs)

    def snapshot(self) -> tuple[dict[str, PredictorFactory], bool]:
        """Copy the mutable state, for :meth:`restore`."""
        return dict(self._factories), self._scanned

    def restore(self, state: tuple[Mapping[str, PredictorFactory], bool]) -> None:
        """Put back a :meth:`snapshot`.

        Provided so a test suite can guarantee :data:`DEFAULT_REGISTRY` is
        unchanged by anything it did, without needing to know the attribute
        names. Prefer constructing a separate :class:`PredictorRegistry` where
        that is possible; this is the escape hatch for exercising the
        module-level functions themselves.
        """
        factories, scanned = state
        self._factories = dict(factories)
        self._scanned = scanned


DEFAULT_REGISTRY = PredictorRegistry()
"""The process-wide registry the module-level functions act on."""


def register(
    factory: PredictorFactory, name: str | None = None, *, replace: bool = False
) -> str:
    """:meth:`PredictorRegistry.register` on :data:`DEFAULT_REGISTRY`."""
    return DEFAULT_REGISTRY.register(factory, name, replace=replace)


def available() -> list[str]:
    """:meth:`PredictorRegistry.available` on :data:`DEFAULT_REGISTRY`."""
    return DEFAULT_REGISTRY.available()


def get(name: str, /, **kwargs: Any) -> SitePredictor:
    """:meth:`PredictorRegistry.get` on :data:`DEFAULT_REGISTRY`."""
    return DEFAULT_REGISTRY.get(name, **kwargs)


def refresh() -> None:
    """:meth:`PredictorRegistry.refresh` on :data:`DEFAULT_REGISTRY`."""
    DEFAULT_REGISTRY.refresh()


def snapshot() -> tuple[dict[str, PredictorFactory], bool]:
    """:meth:`PredictorRegistry.snapshot` on :data:`DEFAULT_REGISTRY`."""
    return DEFAULT_REGISTRY.snapshot()


def restore(state: tuple[Mapping[str, PredictorFactory], bool]) -> None:
    """:meth:`PredictorRegistry.restore` on :data:`DEFAULT_REGISTRY`."""
    DEFAULT_REGISTRY.restore(state)
