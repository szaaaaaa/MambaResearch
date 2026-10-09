"""Colab URL 生成集成。

不做 Colab 远程执行（大方向 plan 锁定不做），只做：
1. 本地 .ipynb → Drive 文件 ID → ``colab.research.google.com/drive/<id>``
2. Drive ID 不可达时 fallback 到 ``colab.research.google.com/drive/upload``
3. GitHub 路径直接拼 ``colab.research.google.com/github/<repo>/blob/<branch>/<path>``
"""
