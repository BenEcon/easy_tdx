"""Diagnostic wrapper for the isolated synthetic QA app; never production."""
import logging

from qa_factor_app import app
from easy_tdx.web import archive_ingress, resource_admission

_retain = resource_admission.Admission.retain


def diagnostic_retain(self):
    try:
        return _retain(self)
    except Exception:
        logging.exception(
            "STALE_CONTEXT refs=%s lost=%s ordinary=%s upload=%s",
            self._refs, self._lost,
            self is resource_admission._current.get(),
            self is archive_ingress._current_upload.get(),
        )
        raise


resource_admission.Admission.retain = diagnostic_retain
