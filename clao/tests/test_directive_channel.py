"""Durable directives: receipt is not consumption; mirrors stay distinguishable."""
import pytest
from loopcore.directives import DirectiveChannel
from loopcore.state_store import StateStore
from tests.sidecar_port.test_mission import _mc


def test_planner_receipt_waits_for_actual_input(tmp_path):
    mc, store = _mc(tmp_path)
    mc.step()
    mc.directives.post('planner','优先边界','cmd')
    mc._apply_directives()
    assert mc.directives.pending_count()==1
    assert mc.directives.records()[0]['status']=='received'
    store.close()
    reader=StateStore(tmp_path/'m.db',readonly=True)
    assert reader.directives(mc.mission.mission_id)[0]['text']=='优先边界'
    reader.close()


def test_mirror_is_not_primary_consumption(tmp_path):
    store=StateStore(tmp_path/'s.db'); channel=DirectiveChannel(store,'m')
    channel.post('verifier','最终核对','cmd')
    with channel.consume('planner','planner:task') as notes:
        assert '最终核对' in notes[0] and '镜像' in notes[0]
    row=channel.records()[0]
    assert row['status']=='received'
    assert row['consumers']['planner:task']['primary'] is False
    with channel.consume('verifier','verifier:mission-final') as notes:
        assert '最终核对' in notes[0]
    assert channel.records()[0]['status']=='applied'
    store.close()


def test_consumer_crash_remains_unknown_not_replayed(tmp_path):
    from loopcore.action_executor import ExternalOperationUnknown
    store=StateStore(tmp_path/'s.db');channel=DirectiveChannel(store,'m')
    channel.post('auditor','核对','cmd')
    with pytest.raises(RuntimeError):
        with channel.consume('auditor','auditor:t'):
            raise RuntimeError('lost confirmation')
    assert channel.records()[0]['status']=='unknown'
    with pytest.raises(ExternalOperationUnknown):
        with channel.consume('auditor','auditor:t'):
            pytest.fail('cannot replay unknown input')
    store.close()


def test_deterministic_targets_are_rejected_without_mirror(tmp_path):
    store=StateStore(tmp_path/'s.db');channel=DirectiveChannel(store,'m')
    for target in ('observer','gate'):
        assert channel.post(target,'x',target).status=='rejected'
    assert channel.notes('planner')==[] and channel.pending_count()==0
    store.close()
