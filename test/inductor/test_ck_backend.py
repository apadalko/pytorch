# Owner(s): ["module: inductor"]
import logging
import os
import unittest

import torch
from torch._inductor import config
from torch._inductor.test_case import run_tests, TestCase

from torch.testing._internal.inductor_utils import HAS_CPU, HAS_CUDA

torch.set_float32_matmul_precision("high")
if HAS_CUDA:
    torch.cuda.memory._set_allocator_settings("expandable_segments:False")

_CUTLASS_DIR = os.path.join(os.path.dirname(__file__), "../../third_party/cutlass/")

log = logging.getLogger(__name__)


def _get_path_without_sccache() -> str:
    """
    Get the PATH environment variable without sccache.
    """
    path_envs = os.environ.get("PATH", "").split(":")
    path_envs = [env for env in path_envs if "/opt/cache/bin" not in env]
    return ":".join(path_envs)


class TestCKBackend(TestCase):
    def setUp(self):
        # The new inductor cache refresh mechanism
        # introduced with https://github.com/pytorch/pytorch/pull/122661
        # interacts badly with persistent subprocesses during
        # autotuning. So we need to disable automatic cache refresh
        # before calling setUp() on the parent class.
        old_disable_fresh_cache_envvar = os.environ.get(
            "INDUCTOR_TEST_DISABLE_FRESH_CACHE", ""
        )
        try:
            os.environ["INDUCTOR_TEST_DISABLE_FRESH_CACHE"] = "1"
            super().setUp()
        finally:
            os.environ[
                "INDUCTOR_TEST_DISABLE_FRESH_CACHE"
            ] = old_disable_fresh_cache_envvar
        torch.random.manual_seed(1234)

    @unittest.skipIf(not torch.version.hip, "ROCM only")
    @unittest.skipIf(config.is_fbcode(), "fbcode requires different CK path setup")
    @unittest.mock.patch.dict(os.environ, {"PATH": _get_path_without_sccache()})
    def test_max_autotune_precompile(self):
        """
        Make sure autotuning mm in subprocesses doesn't crash.
        """

        torch.backends.cuda.matmul.allow_fp16_reduced_precision_reduction = False

        def mm(a, b):
            return a @ b

        tensor_options = {"device": "cuda", "dtype": torch.bfloat16}

        a = torch.randn(2240, 256, **tensor_options)
        b = torch.randn(256, 2048, **tensor_options)

        assert "rocm" in dir(config)

        with config.patch(
            {
                "max_autotune": True,
                "autotune_in_subproc": True,
                "max_autotune_gemm_backends": "CK,Triton,ATen",
                "compile_threads": 2,
                "rocm.n_max_profiling_configs": 2,
            }
        ):
            Y_compiled = torch.compile(mm, dynamic=False)(a, b)
            Y = mm(a, b)
            torch.testing.assert_close(Y_compiled, Y)

    @unittest.skipIf(not torch.version.hip, "ROCM only")
    @unittest.skipIf(config.is_fbcode(), "fbcode requires different CK path setup")
    @unittest.mock.patch.dict(os.environ, {"PATH": _get_path_without_sccache()})
    def test_max_autotune_precompile_preselected(self):
        """
        Make sure autotuning mm in subprocesses doesn't crash.
        """

        torch.backends.cuda.matmul.allow_fp16_reduced_precision_reduction = False

        def mm(a, b):
            return a @ b

        tensor_options = {"device": "cuda", "dtype": torch.float16}

        a = torch.randn(2240, 256, **tensor_options)
        b = torch.randn(2048, 256, **tensor_options).transpose(0, 1)

        assert "rocm" in dir(config)

        with config.patch(
            {
                "max_autotune": True,
                "autotune_in_subproc": True,
                "max_autotune_gemm_backends": "CK,Triton,ATen",
                "compile_threads": 12,
                "rocm.use_preselected_instances": True,
            }
        ):
            Y_compiled = torch.compile(mm, dynamic=False)(a, b)
            Y = mm(a, b)
            torch.testing.assert_close(Y_compiled, Y)


if __name__ == "__main__":
    from torch._inductor.utils import is_big_gpu

    # Set env to make it work in CI.
    if HAS_CUDA and HAS_CPU and is_big_gpu(0):
        run_tests()
