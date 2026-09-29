"""Local-first statement importer for Beancount.

Layers, from the inside out:

- ``core``      domain records, the classifier contract, normalization, rendering
- ``config``    the customer TOML
- ``sources``   statement files to source records
- ``journal``   the decision journal (feature store)
- ``advice``    account candidates derived from past decisions
- ``learning``  harvesting human decisions and reporting accuracy
- ``semantic``  the optional model
- ``app``       composition root: pipeline, Fava importers, command line
- ``csv_demo``  the original 0.1 CSV slice, kept working and self-contained

Only ``app`` is allowed to know about more than one adapter.
"""

__all__: list[str] = []
