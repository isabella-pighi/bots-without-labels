"""Tests for click parsing and feature engineering contracts."""

# pylint: disable=protected-access

from pathlib import Path

import pytest
from scipy.stats import entropy

from bots_without_labels.data import (
    _query_entropy,
    apex_domain,
    build_features,
    parse_clicks,
    select_ml_feature_names,
)


def test_parse_clicks_accepts_header_blank_lines_and_repeated_params(
    tmp_path: Path,
) -> None:
    raw = tmp_path / "clicks.tsv"
    raw.write_text(
        "\n".join(
            [
                "event_id\tevent_time\tregion\tbrowser\tos\turl",
                "",
                "evt_1\t2019-12-02 00:00:00\tMars\tChrome\tiOS\t"
                "/ad_click?d=a.com&q=old&q=new&ttc=10&empty=",
            ]
        ),
        encoding="utf-8",
    )

    events = parse_clicks(raw)

    assert len(events) == 1
    assert events[0].event_id == "evt_1"
    assert events[0].query == "new"
    assert events[0].ttc == 10
    assert events[0].params["empty"] == ""


def test_parse_clicks_accepts_windows_crlf_line_endings(tmp_path: Path) -> None:
    raw = tmp_path / "clicks.tsv"
    raw.write_bytes(
        (
            "event_id\tevent_time\tregion\tbrowser\tos\turl\r\n"
            "evt_1\t2019-12-02 00:00:00\tMars\tChrome\tiOS\t"
            "/ad_click?d=a.com&q=foo&ttc=10\r\n"
        ).encode("utf-8")
    )

    events = parse_clicks(raw)

    assert len(events) == 1
    assert events[0].event_id == "evt_1"
    assert events[0].url == "/ad_click?d=a.com&q=foo&ttc=10"
    assert events[0].ttc == 10


def test_parse_clicks_lowercases_domain_without_stripping_prefixes(
    tmp_path: Path,
) -> None:
    raw = tmp_path / "clicks.tsv"
    raw.write_text(
        "\n".join(
            [
                "evt_1\t2019-12-02 00:00:00\tMars\tChrome\tiOS\t"
                "/ad_click?d=WWW.Shop.Example.COM:443&q=Foo",
                "evt_2\t2019-12-02 00:00:01\tMars\tChrome\tiOS\t"
                "/ad_click?d=m.Example.CO.UK&q=Bar",
            ]
        ),
        encoding="utf-8",
    )

    events = parse_clicks(raw)

    assert events[0].domain == "www.shop.example.com:443"
    assert events[0].params["d"] == "www.shop.example.com:443"
    assert events[0].url.endswith("d=WWW.Shop.Example.COM:443&q=Foo")
    assert events[0].query == "Foo"
    assert events[1].domain == "m.example.co.uk"


def test_apex_domain_normalises_subdomains_and_ports() -> None:
    assert apex_domain("www.amazon.de") == "amazon.de"
    assert apex_domain("Amazon.de") == "amazon.de"
    assert apex_domain("m.example.co.uk") == "example.co.uk"
    assert apex_domain("www.shop.example.com:443") == "example.com"
    assert apex_domain("localhost") == "localhost"
    assert apex_domain("") == ""


def test_query_entropy_uses_scipy_entropy() -> None:
    probabilities = [2 / 6, 2 / 6, 1 / 6, 1 / 6]

    assert _query_entropy("nomnem") == pytest.approx(entropy(probabilities, base=2))


def test_parse_clicks_lowercases_known_categorical_fields_only(
    tmp_path: Path,
) -> None:
    raw = tmp_path / "clicks.tsv"
    raw.write_text(
        "Event_One\t2019-12-02 00:00:00\tMars\tUCBrowser\tiOS\t"
        "/ad_click?d=WWW.Example.COM&ct=GB&kl=UK-EN&q=MiXeD%20Query&"
        "ttc=10&kp=-1&sld=1&n=UP&f=Down&nt=MiX&r=Keep&custom=VALUE\n",
        encoding="utf-8",
    )

    event = parse_clicks(raw)[0]

    assert event.event_id == "Event_One"
    assert event.region == "mars"
    assert event.browser == "ucbrowser"
    assert event.os == "ios"
    assert event.params["d"] == "www.example.com"
    assert event.params["ct"] == "gb"
    assert event.params["kl"] == "uk-en"
    assert event.query == "MiXeD Query"
    assert event.params["ttc"] == "10"
    assert event.params["kp"] == "-1"
    assert event.params["sld"] == "1"
    assert event.params["n"] == "UP"
    assert event.params["f"] == "Down"
    assert event.params["nt"] == "MiX"
    assert event.params["r"] == "Keep"
    assert event.params["custom"] == "VALUE"


def test_parse_clicks_reports_line_number_for_bad_field_count(tmp_path: Path) -> None:
    raw = tmp_path / "clicks.tsv"
    raw.write_text("evt_1\t2019-12-02 00:00:00\tMars\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Line 1 has 3 fields; expected 6"):
        parse_clicks(raw)


def test_parse_clicks_reports_line_number_for_bad_timestamp(tmp_path: Path) -> None:
    raw = tmp_path / "clicks.tsv"
    raw.write_text(
        "\n".join(
            [
                "evt_1\t2019-12-02 00:00:00\tMars\tChrome\tiOS\t/ad_click?d=a.com&q=foo&ttc=10",
                "evt_2\tbad-time\tMars\tChrome\tiOS\t/ad_click?d=a.com&q=foo&ttc=10",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Line 2 has invalid event_time 'bad-time'"):
        parse_clicks(raw)


def test_ttc_infinity_maps_to_missing_value(tmp_path: Path) -> None:
    raw = tmp_path / "clicks.tsv"
    raw.write_text(
        "evt_1\t2019-12-02 00:00:00\tMars\tChrome\tiOS\t"
        "/ad_click?d=a.com&q=foo&ttc=inf\n",
        encoding="utf-8",
    )

    events = parse_clicks(raw)

    assert events[0].ttc == -1


def test_build_features_uses_kp_sld_counts_but_excludes_raw_values(
    tmp_path: Path,
) -> None:
    raw = tmp_path / "clicks.tsv"
    raw.write_text(
        "evt_1\t2019-12-02 00:00:00\tMars\tChrome\tiOS\t"
        "/ad_click?d=a.com&q=foo&ttc=1000&kp=nan&sld=inf\n",
        encoding="utf-8",
    )
    events = parse_clicks(raw)

    feature_names, _ = build_features(events)
    ml_feature_names = select_ml_feature_names(feature_names)

    assert "kp" not in feature_names
    assert "sld" not in feature_names
    assert "log_kp_count" in feature_names
    assert "log_sld_count" in feature_names
    assert "kp" not in ml_feature_names
    assert "sld" not in ml_feature_names
    assert "log_kp_count" in ml_feature_names
    assert "log_sld_count" in ml_feature_names


def test_build_features_adds_apex_domain_counts(tmp_path: Path) -> None:
    raw = tmp_path / "clicks.tsv"
    raw.write_text(
        "\n".join(
            [
                "evt_1\t2019-12-02 00:00:00\tMars\tChrome\tiOS\t"
                "/ad_click?d=www.amazon.de&q=nomnem&ttc=1000",
                "evt_2\t2019-12-02 00:00:01\tMars\tChrome\tiOS\t"
                "/ad_click?d=m.amazon.de&q=nomnem&ttc=1100",
                "evt_3\t2019-12-02 00:00:02\tMars\tChrome\tiOS\t"
                "/ad_click?d=amazon.de&q=nomnem&ttc=1200",
            ]
        ),
        encoding="utf-8",
    )
    events = parse_clicks(raw)

    feature_names, _ = build_features(events)
    feature_index = {name: idx for idx, name in enumerate(feature_names)}

    assert events[0].apex_domain == "amazon.de"
    assert events[0].pld_click_count == 3
    assert feature_names.index("pld_click_count") == 1
    assert feature_names.index("log_apex_domain_count") == 2
    assert feature_names.index("log_query_apex_domain_count") == 5
    assert events[0].features[feature_index["log_domain_count"]] == pytest.approx(
        0.693147
    )
    assert events[0].features[feature_index["pld_click_count"]] == pytest.approx(3.0)
    assert events[0].features[feature_index["log_apex_domain_count"]] == pytest.approx(
        1.386294
    )
    assert events[0].features[
        feature_index["log_query_apex_domain_count"]
    ] == pytest.approx(1.386294)


def test_build_features_uses_uniform_ml_feature_weights(tmp_path: Path) -> None:
    raw = tmp_path / "clicks.tsv"
    raw.write_text(
        "\n".join(
            [
                "evt_1\t2019-12-02 00:00:00\tMars\tChrome\tiOS\t"
                "/ad_click?d=a.com&q=foo&ttc=1000&kp=1&sld=0",
                "evt_2\t2019-12-02 00:00:01\tMars\tChrome\tiOS\t"
                "/ad_click?d=b.com&q=bar&ttc=2000&kp=1&sld=1",
                "evt_3\t2019-12-02 00:00:02\tMars\tChrome\tiOS\t"
                "/ad_click?d=c.com&q=baz&ttc=3000&kp=2&sld=1",
            ]
        ),
        encoding="utf-8",
    )
    events = parse_clicks(raw)

    feature_names, _ = build_features(events)
    ml_feature_names = select_ml_feature_names(feature_names)

    assert len(events[0].ml_feature_weights) == len(ml_feature_names)
    assert set(events[0].ml_feature_weights) == {1.0}
