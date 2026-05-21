# TestModule

The host-mountable container under `/_test`. Aggregates all
test-infrastructure submodules. Refuses to instantiate outside a local
dev server *or* when [`activate()`][viur.testing.activation.activate] has
not run.

::: viur.testing._test.TestModule
    options:
      heading_level: 2
      show_source: true
      members_order: source
