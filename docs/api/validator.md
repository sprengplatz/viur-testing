# Validators

Two `RequestValidator` subclasses that hook into viur-core's
`Router.requestValidators` chain. You rarely instantiate them yourself
— [`activate()`](host.md#activate) installs `TokenValidator`,
[`protect()`](host.md#protect) installs `ProductionGuardValidator`.

## TokenValidator

::: viur.testing.validator.TokenValidator
    options:
      heading_level: 3
      show_source: true

## ProductionGuardValidator

::: viur.testing.validator.ProductionGuardValidator
    options:
      heading_level: 3
      show_source: true
