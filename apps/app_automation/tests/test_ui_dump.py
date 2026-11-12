from apps.app_automation.recording.adb_gateway import hierarchy_xml


def test_error_output_is_not_used_as_the_current_page():
    old = '<hierarchy><node text="2000人群_48" /></hierarchy>'
    assert hierarchy_xml("ERROR: could not get idle state.", old) == ""


def test_fresh_hierarchy_is_kept():
    xml = '<hierarchy><node text="Discover" /></hierarchy>'
    assert hierarchy_xml("UI hierchary dumped to: /sdcard/testhub-uidump.xml", xml) == xml
