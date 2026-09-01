import json
import os
from collections import defaultdict
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from bookings.models import (
    LEGACY_ACCESS_RULE_FIELDS,
    LegacyAccessPreset,
    LegacyUserProfile,
)


class Command(BaseCommand):
    help = "Synchronise legacy MySQL users and access rules into Django securely."

    def add_arguments(self, parser):
        parser.add_argument(
            "--config",
            default=os.getenv("LEGACY_MYSQL_CONFIG"),
            help="Path to the protected legacy MySQL JSON profile.",
        )
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        if not options["config"]:
            raise CommandError("Pass --config or set LEGACY_MYSQL_CONFIG.")
        dataset = self.read_dataset(
            options["config"],
            include_passwords=not options["dry_run"],
        )
        dataset = self.validate_dataset(
            dataset,
            require_passwords=not options["dry_run"],
        )
        if options["dry_run"]:
            summary = self.dataset_summary(dataset)
            self.stdout.write(f"Dry run only; no PostgreSQL writes: {summary}")
            return
        summary = self.sync_dataset(dataset)
        self.stdout.write(self.style.SUCCESS(f"Legacy users synced: {summary}"))

    def read_dataset(self, config_path, include_passwords=True):
        config = self._load_config(config_path)
        try:
            import mysql.connector

            connection = mysql.connector.connect(
                host=config["host"],
                port=config["port"],
                user=config["user"],
                password=config["password"],
                database=config["database"],
                connection_timeout=15,
            )
        except Exception as exc:
            raise CommandError("Could not connect to the legacy MySQL database.") from exc

        cursor = connection.cursor(dictionary=True)
        try:
            cursor.execute("SET SESSION TRANSACTION READ ONLY")
            cursor.execute("START TRANSACTION READ ONLY")
            cursor.execute(self._preset_sql())
            presets = cursor.fetchall()
            cursor.execute(self._users_sql(include_passwords))
            users = cursor.fetchall()
            return {"presets": presets, "users": users}
        except Exception as exc:
            raise CommandError("Could not read legacy users and access rules.") from exc
        finally:
            cursor.close()
            connection.close()

    @staticmethod
    def _load_config(config_path):
        try:
            raw = json.loads(Path(config_path).expanduser().read_text())
            if not isinstance(raw, dict):
                raise ValueError
            return {
                "host": str(raw["host"]),
                "port": int(raw.get("port", 3306)),
                "user": str(raw["user"]),
                "password": str(raw["password"]),
                "database": str(raw["database"]),
            }
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise CommandError("The legacy MySQL configuration is invalid.") from exc

    @staticmethod
    def dataset_summary(dataset):
        groups = {
            str(row.get("username", "")).strip().casefold()
            for row in dataset["users"]
            if str(row.get("username", "")).strip()
        }
        return {
            "presets": len(dataset["presets"]),
            "source_users": len(dataset["users"]),
            "unique_usernames": len(groups),
            "duplicate_rows": len(dataset["users"]) - len(groups),
        }

    @classmethod
    def validate_dataset(cls, dataset, require_passwords=True):
        try:
            if not isinstance(dataset, dict):
                raise ValueError
            presets = []
            preset_ids = set()
            for source in dataset["presets"]:
                row = dict(source)
                legacy_id = cls._strict_nonnegative_int(row["legacy_id"], allow_zero=False)
                description = row["description"]
                if legacy_id in preset_ids or not isinstance(description, str) or not description.strip():
                    raise ValueError
                row["legacy_id"] = legacy_id
                row["description"] = description.strip()
                row.update(cls._rule_values(row))
                presets.append(row)
                preset_ids.add(legacy_id)

            users = []
            user_ids = set()
            for source in dataset["users"]:
                row = dict(source)
                legacy_id = cls._strict_nonnegative_int(row["legacy_id"], allow_zero=False)
                username = row["username"]
                dormant = cls._strict_bool(row["dormant"])
                password = row["plaintext_password"]
                if (
                    legacy_id in user_ids
                    or not isinstance(username, str)
                    or not username.strip()
                    or not isinstance(password, str)
                    or (require_passwords and not dormant and not password)
                ):
                    raise ValueError
                for field in ("first_name", "last_name", "email"):
                    if row.get(field) is not None and not isinstance(row[field], str):
                        raise ValueError
                row["legacy_id"] = legacy_id
                row["username"] = username.strip()
                row["dormant"] = dormant
                row["access_type"] = cls._strict_nonnegative_int(row["access_type"])
                row["assigned_desk"] = cls._strict_nonnegative_int(row["assigned_desk"])
                row.update(cls._rule_values(row))
                users.append(row)
                user_ids.add(legacy_id)
            return {"presets": presets, "users": users}
        except (KeyError, TypeError, ValueError):
            raise CommandError(
                "Legacy user import stopped because the source contains invalid security data."
            ) from None

    @transaction.atomic
    def sync_dataset(self, dataset):
        presets = {}
        source_preset_ids = set()
        for row in dataset["presets"]:
            legacy_id = int(row["legacy_id"])
            defaults = {
                "description": str(row["description"] or f"Preset {legacy_id}"),
                **self._rule_values(row),
            }
            preset, _ = LegacyAccessPreset.objects.update_or_create(
                legacy_mysql_id=legacy_id,
                defaults=defaults,
            )
            presets[legacy_id] = preset
            source_preset_ids.add(legacy_id)

        grouped = defaultdict(list)
        for row in dataset["users"]:
            username = str(row.get("username", "")).strip()
            if username:
                grouped[username.casefold()].append(row)

        canonical_rows = [
            sorted(rows, key=lambda row: (bool(row["dormant"]), int(row["legacy_id"])))[0]
            for rows in grouped.values()
        ]
        canonical_rows.sort(key=lambda row: int(row["legacy_id"]))

        user_model = get_user_model()
        touched_profiles = set()
        imported = 0
        conflicts = 0
        for row in canonical_rows:
            legacy_id = int(row["legacy_id"])
            username = str(row["username"]).strip()
            profile = LegacyUserProfile.objects.select_related("user").filter(
                legacy_mysql_id=legacy_id
            ).first()
            user = profile.user if profile else None

            collisions = user_model.objects.filter(username__iexact=username)
            if user:
                collisions = collisions.exclude(pk=user.pk)
            if collisions.exists():
                conflicts += 1
                if user:
                    user.is_active = False
                    user.is_staff = False
                    user.set_unusable_password()
                    user.save(update_fields=["is_active", "is_staff", "password"])
                    touched_profiles.add(profile.pk)
                continue

            if user is None:
                candidate = user_model.objects.filter(username__iexact=username).first()
                candidate_profile = None
                if candidate:
                    candidate_profile = LegacyUserProfile.objects.filter(user=candidate).first()
                if candidate and candidate_profile is None:
                    conflicts += 1
                    continue
                user = candidate or user_model(username=username)
                profile = candidate_profile

            is_active = not bool(row["dormant"])
            user.username = username
            user.first_name = str(row.get("first_name") or "")[:150]
            user.last_name = str(row.get("last_name") or "")[:150]
            user.email = str(row.get("email") or "")[:254]
            user.is_active = is_active
            user.is_staff = is_active
            user.is_superuser = False
            plaintext_password = str(row.get("plaintext_password") or "")
            if is_active and plaintext_password:
                if not user.check_password(plaintext_password):
                    user.set_password(plaintext_password)
            else:
                user.set_unusable_password()
            user.save()

            access_type = int(row.get("access_type") or 0)
            profile_defaults = {
                "access_type": access_type,
                "preset": presets.get(access_type),
                "assigned_desk": int(row.get("assigned_desk") or 0),
                **self._rule_values(row),
            }
            if profile is None:
                profile = LegacyUserProfile.objects.create(
                    user=user,
                    legacy_mysql_id=legacy_id,
                    **profile_defaults,
                )
            else:
                profile.legacy_mysql_id = legacy_id
                for field, value in profile_defaults.items():
                    setattr(profile, field, value)
                profile.save()
            touched_profiles.add(profile.pk)
            imported += 1

        for profile in LegacyUserProfile.objects.select_related("user").exclude(
            pk__in=touched_profiles
        ):
            user = profile.user
            user.is_active = False
            user.is_staff = False
            user.set_unusable_password()
            user.save(update_fields=["is_active", "is_staff", "password"])

        LegacyAccessPreset.objects.exclude(
            legacy_mysql_id__in=source_preset_ids
        ).delete()

        summary = self.dataset_summary(dataset)
        summary.update({"imported": imported, "conflicts": conflicts})
        return summary

    @staticmethod
    def _rule_values(row):
        values = {}
        for field in LEGACY_ACCESS_RULE_FIELDS:
            raw = row.get(field)
            values[field] = (
                None
                if field == "assign_cons" and raw is None
                else Command._strict_bool(raw)
            )
        return values

    @staticmethod
    def _strict_bool(value):
        if isinstance(value, bool):
            return value
        if isinstance(value, int) and value in (0, 1):
            return bool(value)
        raise ValueError

    @staticmethod
    def _strict_nonnegative_int(value, allow_zero=True):
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError
        if value < 0 or (not allow_zero and value == 0):
            raise ValueError
        return value

    @staticmethod
    def _preset_sql():
        columns = ", ".join(LEGACY_ACCESS_RULE_FIELDS)
        return (
            "SELECT no AS legacy_id, descr AS description, "
            f"{columns} FROM tbl_user_access_presets ORDER BY no"
        )

    @staticmethod
    def _users_sql(include_passwords=True):
        columns = ", ".join(LEGACY_ACCESS_RULE_FIELDS)
        password_projection = (
            "password AS plaintext_password"
            if include_passwords
            else "'' AS plaintext_password"
        )
        return (
            "SELECT no AS legacy_id, access_type, username, "
            f"{password_projection}, dormant, assigned_desk, "
            "first_name, last_name, email, "
            f"{columns} FROM tbl_users ORDER BY no"
        )
