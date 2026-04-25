"""Policy engine tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from linuxagent.interfaces import CommandSource, SafetyLevel
from linuxagent.policy import DEFAULT_POLICY_ENGINE, PolicyEngine, load_policy_config
from linuxagent.policy.config_rules import PolicyConfigError
from linuxagent.policy.models import PolicyConfig, PolicyMatch, PolicyRule


def test_policy_decision_exposes_capabilities_and_approval() -> None:
    decision = DEFAULT_POLICY_ENGINE.evaluate("systemctl restart nginx")

    assert decision.level is SafetyLevel.CONFIRM
    assert decision.risk_score >= 70
    assert "service.mutate" in decision.capabilities
    assert decision.matched_rules == ("DESTRUCTIVE",)
    assert decision.approval.required is True


def test_policy_llm_first_run_adds_source_capability() -> None:
    decision = DEFAULT_POLICY_ENGINE.evaluate("ls -la", source=CommandSource.LLM)

    assert decision.level is SafetyLevel.CONFIRM
    assert decision.matched_rules == ("LLM_FIRST_RUN",)
    assert "llm.generated" in decision.capabilities


def test_policy_config_loads_default_yaml() -> None:
    path = Path(__file__).resolve().parents[3] / "configs" / "policy.default.yaml"
    config = load_policy_config(path)

    assert config.version == 1
    assert len(config.rules) >= 7


def test_policy_config_rejects_duplicate_rule_ids() -> None:
    raw_rule = {
        "id": "duplicate",
        "legacy_rule": "DESTRUCTIVE",
        "level": "CONFIRM",
        "risk_score": 50,
        "capabilities": ["test"],
        "reason": "test",
        "match": {"command": ["rm"]},
    }

    with pytest.raises(ValueError, match="unique"):
        PolicyConfig.model_validate({"rules": [raw_rule, raw_rule]})


def test_policy_config_rejects_invalid_yaml_shape(tmp_path: Path) -> None:
    path = tmp_path / "policy.yaml"
    path.write_text("- not-a-mapping\n", encoding="utf-8")

    with pytest.raises(PolicyConfigError, match="top-level"):
        load_policy_config(path)


def test_custom_policy_rule_can_override_decision_shape() -> None:
    engine = PolicyEngine(
        PolicyConfig(
            rules=(
                PolicyRule(
                    id="custom.restart",
                    legacy_rule="CUSTOM_RESTART",
                    level=SafetyLevel.CONFIRM,
                    risk_score=88,
                    capabilities=("custom.service",),
                    reason="custom restart",
                    match=PolicyMatch(command=("systemctl",), subcommand_any=("restart",)),
                ),
            )
        )
    )

    decision = engine.evaluate("systemctl restart nginx")

    assert decision.level is SafetyLevel.CONFIRM
    assert decision.risk_score == 88
    assert decision.capabilities == ("custom.service",)
    assert decision.matched_rules == ("CUSTOM_RESTART",)


DANGEROUS_GOLDEN_CASES = (
    # filesystem delete / mutation
    "rm -rf /tmp/a",
    "rm -fr /tmp/a",
    "rm --force /tmp/a",
    "rm -r /var/tmp/a",
    "rm -R /opt/app/cache",
    "rmdir /tmp/empty",
    "shred /tmp/secret",
    "wipefs /dev/sdb",
    "find /tmp -name '*.tmp' -delete",
    "find /var/log -type f -delete",
    "truncate -s 0 /var/log/app.log",
    "truncate --size 0 /tmp/file",
    "chmod -R 777 /srv/app",
    "chmod --recursive go+w /srv/app",
    "chown -R root:root /srv/app",
    "chown --recursive app:app /srv/app",
    "tee /etc/nginx/nginx.conf",
    "sed -i s/a/b/ /etc/hosts",
    "cp new.conf /etc/app.conf",
    "mv new.conf /etc/app.conf",
    # root / sensitive / embedded
    "rm -rf /",
    "cat /etc/shadow",
    "cat /etc/gshadow",
    "cat /etc/sudoers",
    "cat /boot/grub/grub.cfg",
    "cat /dev/sda",
    "cat /dev/nvme0n1",
    "cat /proc/1/environ",
    "cat /sys/kernel/uevent_helper",
    "echo 'rm -rf /'",
    "echo $(whoami)",
    "echo `whoami`",
    ":(){ :|: & };:",
    "mkfs.ext4 /dev/sdb1",
    "mkfs.xfs /dev/sdb1",
    "dd if=/dev/zero of=/tmp/x",
    "dd of=/tmp/x if=/dev/zero",
    "fdisk /dev/sdb",
    "parted /dev/sdb print",
    "mkswap /dev/sdb2",
    # services
    "systemctl stop nginx",
    "systemctl restart nginx",
    "systemctl reload nginx",
    "systemctl disable nginx",
    "systemctl enable nginx",
    "systemctl mask nginx",
    "systemctl kill nginx",
    "systemctl poweroff",
    "systemctl reboot",
    "systemctl halt",
    "service nginx stop",
    "service nginx restart",
    # packages
    "apt remove nginx",
    "apt purge nginx",
    "apt autoremove",
    "apt-get remove nginx",
    "apt-get purge nginx",
    "yum remove nginx",
    "yum erase nginx",
    "dnf remove nginx",
    "dnf autoremove",
    "pacman -R nginx",
    "pacman -Rs nginx",
    "pacman -Rns nginx",
    # containers
    "docker rm web",
    "docker rmi image",
    "docker kill web",
    "docker prune",
    "docker system prune",
    "docker stop web",
    "docker restart web",
    "docker compose down",
    "docker volume rm data",
    "docker network rm net",
    # kubernetes / helm
    "kubectl delete pod web",
    "kubectl drain node-a",
    "kubectl cordon node-a",
    "kubectl replace -f deploy.yaml",
    "kubectl apply -f deploy.yaml",
    "kubectl patch deployment web -p '{}'",
    "kubectl scale deployment web --replicas=0",
    "kubectl rollout restart deployment web",
    "helm uninstall web",
    "helm delete web",
    "helm rollback web 1",
    "helm upgrade web chart/",
    "helm install web chart/",
    # git / network / identity / cron / sudo
    "git push origin main",
    "git reset --hard HEAD~1",
    "git clean -fdx",
    "git checkout -- file",
    "git rebase main",
    "iptables -F",
    "iptables -A INPUT -j DROP",
    "nft flush ruleset",
    "ufw disable",
    "ufw deny 22",
    "firewall-cmd --reload",
    "userdel app",
    "groupdel app",
    "passwd -d app",
    "passwd --delete app",
    "crontab -r",
    "sudo systemctl restart nginx",
    "sudo rm -rf /tmp/a",
    "sudo apt remove nginx",
    "sudo reboot",
    "sudo iptables -F",
    # interactive / privileged shells
    "python script.py",
    "python3 script.py",
    "bash",
    "sh",
    "ssh host",
    "mysql -uroot",
    "psql postgres",
    "redis-cli",
)


def test_dangerous_golden_cases_are_not_safe() -> None:
    assert len(DANGEROUS_GOLDEN_CASES) >= 100
    for command in DANGEROUS_GOLDEN_CASES:
        decision = DEFAULT_POLICY_ENGINE.evaluate(command)
        assert decision.level is not SafetyLevel.SAFE, command
        assert decision.capabilities, command
        assert decision.matched_rules, command
