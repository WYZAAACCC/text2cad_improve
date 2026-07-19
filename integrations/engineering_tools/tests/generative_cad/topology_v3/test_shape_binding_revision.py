"""Phase 3 tests — ObjectStore revision tracking and locator staleness."""

import pytest

from seekflow_engineering_tools.generative_cad.runtime.object_store import RuntimeObjectStore
from seekflow_engineering_tools.generative_cad.topology.locator import RuntimeTopoLocator


class TestObjectStoreRevisions:
    """V3: ObjectStore revision tracking for locator staleness detection."""

    def test_put_sets_initial_revision(self):
        store = RuntimeObjectStore()
        handle = type('Handle', (), {'id': 'solid:test_n1:body', 'type': 'solid'})()
        store.put(handle, object())
        assert store.get_revision('solid:test_n1:body') == 1

    def test_replace_bumps_revision(self):
        store = RuntimeObjectStore()
        handle = type('Handle', (), {'id': 'solid:test_n1:body', 'type': 'solid'})()
        store.put(handle, object())
        assert store.get_revision('solid:test_n1:body') == 1
        store.replace(handle, object())  # same body, rebuilt
        assert store.get_revision('solid:test_n1:body') == 2

    def test_replace_nonexistent_raises(self):
        store = RuntimeObjectStore()
        handle = type('Handle', (), {'id': 'solid:test_n1:body', 'type': 'solid'})()
        with pytest.raises(KeyError, match="Cannot replace"):
            store.replace(handle, object())

    def test_multiple_replace_bumps_monotonically(self):
        store = RuntimeObjectStore()
        handle = type('Handle', (), {'id': 'solid:test_n1:body', 'type': 'solid'})()
        store.put(handle, object())
        for i in range(5):
            store.replace(handle, object())
            assert store.get_revision('solid:test_n1:body') == i + 2

    def test_get_revision_unknown_returns_zero(self):
        store = RuntimeObjectStore()
        assert store.get_revision('nonexistent') == 0


class TestLocatorRevisionStaleness:
    """V3: Locator is_stale_v3() uses revision token."""

    def test_legacy_locator_no_revision_is_not_stale(self):
        loc = RuntimeTopoLocator(
            owner_body_handle_id='solid:test_n1:body',
            entity_type='face', indexed_map_position=1, occt_shape_hash=0,
        )
        assert not loc.is_stale_v3(current_revision='5')

    def test_v3_locator_revision_mismatch_is_stale(self):
        loc = RuntimeTopoLocator(
            owner_body_handle_id='solid:test_n1:body',
            entity_type='face', indexed_map_position=1, occt_shape_hash=0,
            owner_body_revision_id='1',
        )
        assert loc.is_stale_v3(current_revision='3')

    def test_v3_locator_revision_match_is_fresh(self):
        loc = RuntimeTopoLocator(
            owner_body_handle_id='solid:test_n1:body',
            entity_type='face', indexed_map_position=1, occt_shape_hash=0,
            owner_body_revision_id='3',
        )
        assert not loc.is_stale_v3(current_revision='3')

    def test_v3_locator_fields_in_model_dump(self):
        loc = RuntimeTopoLocator(
            owner_body_handle_id='solid:test_n1:body',
            entity_type='face', indexed_map_position=1, occt_shape_hash=0,
            owner_body_revision_id='2',
        )
        data = loc.model_dump()
        assert data['owner_body_revision_id'] == '2'
        assert data['map_algorithm'] == 'occt_indexed_map_v1'
