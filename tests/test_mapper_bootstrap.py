from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_bot_mapper_bootstrap_without_manual_related_imports() -> None:
    project_root = Path(__file__).resolve().parents[1]
    command = [
        sys.executable,
        "-c",
        (
            "from sqlalchemy.orm import configure_mappers; "
            "from tg_bot_aggregator.domain.bots.models import Bot; "
            "configure_mappers(); "
            "print('MAPPERS_OK')"
        ),
    ]
    result = subprocess.run(
        command,
        cwd=project_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, (
        "bot mapper bootstrap failed without explicit related model imports\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}\n"
    )
