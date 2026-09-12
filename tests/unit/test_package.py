from importlib.metadata import version

import pytest


@pytest.mark.smoke
def test_package_is_importable() -> None:
    import enterprise_employee_agent

    assert enterprise_employee_agent.__version__ == version("enterprise-employee-agent")
