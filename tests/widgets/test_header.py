from cctop.widgets.header import Header


def test_header_includes_name_label() -> None:
    header = Header()
    rendered = header.render().plain
    assert "NAME" in rendered
