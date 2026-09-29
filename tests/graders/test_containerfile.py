from acb_graders.containerfile import parse, parse_image_ref


def test_image_refs():
    assert parse_image_ref("node").fully_qualified is False
    ref = parse_image_ref("docker.io/library/node:22-slim@sha256:abc")
    assert (ref.registry, ref.repository, ref.tag, ref.digest) == ("docker.io", "library/node", "22-slim", "sha256:abc")
    assert parse_image_ref("localhost:5000/app").registry == "localhost:5000"
    assert parse_image_ref("quay.io/podman/stable").tag is None


def test_stages_args_and_continuations():
    cf = parse(
        """# syntax=docker/dockerfile:1
ARG BASE=docker.io/library/golang:1.25
FROM ${BASE} AS build
RUN apt-get update && \\
    apt-get install -y git
COPY . .
FROM build AS test
FROM gcr.io/distroless/static:nonroot
COPY --from=build /out /app
CMD ["/app"]
"""
    )
    assert [s.base for s in cf.stages] == ["docker.io/library/golang:1.25", "build", "gcr.io/distroless/static:nonroot"]
    assert cf.stages[1].base_stage is cf.stages[0]
    assert [i.raw for i in cf.external_images()] == ["docker.io/library/golang:1.25", "gcr.io/distroless/static:nonroot"]
    run = cf.stages[0].find("RUN")[0]
    assert "apt-get install -y git" in run.args and run.line == 4
    final = cf.final_stage
    assert final.find("COPY")[0].flags() == {"from": "build"}
    assert final.find("CMD")[0].is_exec_form


def test_heredoc_is_one_instruction():
    cf = parse("FROM quay.io/fedora/fedora:45\nRUN <<EOF\ndnf -y install git\ndnf clean all\nEOF\nCMD [\"bash\"]\n")
    assert [i.keyword for i in cf.instructions] == ["FROM", "RUN", "CMD"]
    assert "dnf clean all" in cf.instructions[1].args
