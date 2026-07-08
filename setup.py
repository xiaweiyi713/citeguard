"""Legacy setuptools entry point for older editable-install tooling."""

from setuptools import find_packages, setup


setup(
    name="citeguard",
    version="0.1.0",
    description="A skeptical citation auditor for agent writing workflows.",
    long_description=open("README.md", encoding="utf-8").read(),
    long_description_content_type="text/markdown",
    python_requires=">=3.9",
    license_files=["LICENSE"],
    packages=find_packages(include=["citeguard", "citeguard.*"]),
    keywords=[
        "citation-verification",
        "skeptical-citation-auditor",
        "agent-tools",
        "mcp",
        "scientific-writing",
        "claim-support",
        "research-integrity",
        "hallucination-mitigation",
        "evidence-attribution",
    ],
    include_package_data=True,
    package_data={"citeguard": ["py.typed"]},
    url="https://github.com/xiaweiyi713/citeguard",
    project_urls={
        "Homepage": "https://github.com/xiaweiyi713/citeguard",
        "Repository": "https://github.com/xiaweiyi713/citeguard",
        "Issues": "https://github.com/xiaweiyi713/citeguard/issues",
        "Changelog": "https://github.com/xiaweiyi713/citeguard/blob/main/CHANGELOG.md",
        "Documentation": "https://github.com/xiaweiyi713/citeguard#readme",
    },
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Science/Research",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Topic :: Scientific/Engineering :: Artificial Intelligence",
        "Topic :: Scientific/Engineering :: Information Analysis",
        "Topic :: Text Processing :: Linguistic",
        "Typing :: Typed",
    ],
    install_requires=[],
    extras_require={
        "api": [
            "fastapi>=0.115,<1.0",
            "uvicorn>=0.30,<1.0",
        ],
        "models": [
            "sentence-transformers==3.1.1",
            "transformers==4.45.2",
            "torch==2.3.1",
            "safetensors==0.7.0",
        ],
        "mcp": [
            "mcp>=1.2",
        ],
        "pdf": [
            "pypdf>=4,<6",
        ],
    },
    entry_points={
        "console_scripts": [
            "citeguard=citeguard.cli:main",
            "citeguard-mcp=citeguard.mcp.server:main",
        ],
    },
)
