# Check Nebius defaults, campaign paths, and required environment settings.
from backends.nebius import config

def test_h100_platform_defaults():
    assert config.GPU_PLATFORM == "gpu-h100-sxm"
    assert config.GPU_PRESET == "1gpu-16vcpu-200gb"
    assert config.REGION == "eu-north1"
    assert config.BOOT_IMAGE_FAMILY == "ubuntu24.04-cuda12"

def test_paths_are_under_nebius_dir():
    assert config.OUTPUTS_DIR.name == "outputs"
    assert config.CHECKPOINTS_DIR.name == "checkpoints"
    assert "nebius" in str(config.OUTPUTS_DIR)

def test_required_env_ids_have_accessors():
    assert hasattr(config, "project_id")
    assert hasattr(config, "subnet_id")
