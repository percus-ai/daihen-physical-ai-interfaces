import interfaces_backend.utils.torch_info as torch_info_module


def test_get_torch_info_uses_cuda_smoke_test_result(monkeypatch) -> None:
    torch_info_module.clear_cache()
    monkeypatch.setattr(
        torch_info_module,
        "run_torch_runtime_probe",
        lambda **kwargs: (
            True,
            {
                "torch_version": "2.12.0.dev20260401+cu128",
                "cuda_available": True,
                "cuda_version": "12.8",
                "gpu_name": "RTX 4090",
                "gpu_count": 1,
                "mps_available": False,
                "cuda_memory_total": 24564.0,
                "cuda_memory_free": 24000.0,
                "gpu_capability": "sm_89",
                "cuda_compatible": True,
                "cuda_runtime_smoke_test": True,
                "cuda_supported_arches": ["sm_75", "sm_80", "sm_86", "sm_90"],
                "cuda_arch_exact_match": False,
                "torchvision_version": "0.0.test",
                "torchaudio_version": "0.0.test",
                "error": None,
            },
        ),
    )

    info = torch_info_module.get_torch_info(use_cache=False)

    assert info["torch_version"] == "2.12.0.dev20260401+cu128"
    assert info["gpu_capability"] == "sm_89"
    assert info["cuda_supported_arches"] == ["sm_75", "sm_80", "sm_86", "sm_90"]
    assert info["cuda_arch_exact_match"] is False
    assert info["cuda_compatible"] is True
    assert info["cuda_runtime_smoke_test"] is True


def test_get_torch_info_surfaces_probe_failure(monkeypatch) -> None:
    torch_info_module.clear_cache()
    monkeypatch.setattr(
        torch_info_module,
        "run_torch_runtime_probe",
        lambda **kwargs: (
            False,
            {
                "error": "torch runtime probe failed",
                "stderr": "ImportError: broken torch",
            },
        ),
    )

    info = torch_info_module.get_torch_info(use_cache=False)

    assert info["torch_version"] is None
    assert info["error"] == "ImportError: broken torch"
