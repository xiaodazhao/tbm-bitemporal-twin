from __future__ import annotations

from tbm_twin.process.episode_builder import build_excavation_episodes
from tbm_twin.process.weak_labels import label_operation_phases
from tbm_twin.validation.config import load_validation_config
from tbm_twin.validation.visualization import write_episode_review_plot
from tests.conftest import base_rows, normalize_rows


def test_episode_review_plot_writes_png(tmp_path, catalog) -> None:
    labeled = label_operation_phases(normalize_rows(tmp_path, base_rows(), catalog))
    episodes = build_excavation_episodes(labeled)
    output = tmp_path / "episode_review.png"

    warnings = write_episode_review_plot(
        date="2023-12-30",
        labeled_frame=labeled,
        episodes=episodes,
        output_path=output,
        config=load_validation_config(),
    )

    assert warnings == []
    assert output.exists()


def test_episode_review_plot_failure_returns_warning(tmp_path, catalog) -> None:
    labeled = label_operation_phases(normalize_rows(tmp_path, base_rows(), catalog))
    episodes = build_excavation_episodes(labeled)
    bad_output_path = tmp_path

    warnings = write_episode_review_plot(
        date="2023-12-30",
        labeled_frame=labeled,
        episodes=episodes,
        output_path=bad_output_path,
        config=load_validation_config(),
    )

    assert warnings
    assert "episode_review_plot_failed" in warnings[0]
