from cx_Freeze import setup, Executable

setup(
    name="MiniVideoStudio",
    version="1.0.0",
    description="Central de ferramentas para converter, comprimir, cortar e analisar vídeos e áudios, com interface desktop moderna e processamento 100%% local.",
    options={"build_exe": {
        "packages": ["ui", "core", "utils", "tkinter", "PIL"],   # ui/core/utils: carregados por nome (importlib)
        "excludes": ["unittest", "test"],
        "include_files": ["MiniVideoStudio.ico"],                              # opcional: ["installer/ffmpeg_bundle/ffmpeg", "ffmpeg"]
    }},
    executables=[Executable("main.py", base="gui", icon="MiniVideoStudio.ico", target_name="MiniVideoStudio.exe")],
)