# Host API

The four functions a host project's `main.py` and `modules/__init__.py`
typically reach for. `setup()` and `register_modules()` are wrappers
that hide the low-level details and are sufficient for most projects;
`activate()` and `protect()` are the primitives behind them and are
useful when you need finer control.

## setup

::: viur.testing.setup
    options:
      heading_level: 3
      show_source: true

## register_modules

::: viur.testing.register_modules
    options:
      heading_level: 3
      show_source: true

## activate

::: viur.testing.activation.activate
    options:
      heading_level: 3
      show_source: true

## protect

::: viur.testing.protection.protect
    options:
      heading_level: 3
      show_source: true
