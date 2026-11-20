from config.universe import build_sector_peer_groups, load_universe, solo_tickers


def test_universe_has_30_unique_tickers():
    df = load_universe()
    assert len(df) == 30
    assert df["ticker"].is_unique
    assert (df["yahoo_symbol"] == df["ticker"] + ".IS").all()


def test_each_ticker_in_exactly_one_peer_group():
    groups = build_sector_peer_groups()
    all_members = [t for members in groups.values() for t in members]
    assert len(all_members) == len(set(all_members)) == 30


def test_peer_group_size_matches_real_member_count():
    df = load_universe()
    real = df.groupby("peer_group")["ticker"].transform("count")
    assert (df["peer_group_size"] == real).all()


def test_expected_groups_and_solos():
    groups = build_sector_peer_groups()
    assert groups["retail"] == ["BIMAS", "MAVI", "MGROS"]
    assert groups["energy_petrochem"] == ["PETKM", "TUPRS"]
    assert groups["chemicals"] == ["GUBRF", "SASA"]
    assert solo_tickers() == sorted(
        ["ASELS", "AKBNK", "KCHOL", "CCOLA", "TRALT", "ENKAI", "EKGYO", "TURSG", "OYAKC", "ISMEN", "ARCLK"]
    )
