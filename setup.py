"""pyproject.toml holds the package's metadata. This only puts SONG_FORMAT.md beside gui.html in a built package, as
tools/build_exe.py does for the exe: the Pattern tab's effect help reads its tables (gui.effect_help)."""
from setuptools import setup
from setuptools.command.build_py import build_py


class BuildPy(build_py):
    def run(self):
        super().run()
        self.mkpath(f"{self.build_lib}/vulturetracker")  # an editable build has not made it
        self.copy_file("SONG_FORMAT.md", f"{self.build_lib}/vulturetracker/SONG_FORMAT.md")


setup(cmdclass={"build_py": BuildPy})
