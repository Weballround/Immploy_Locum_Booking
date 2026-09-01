import json
import os
from datetime import date, datetime
from decimal import Decimal
from decimal import InvalidOperation
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from bookings.candidate_locations import canonical_candidate_region
from bookings.models import (
    Candidate,
    CandidateProfileOption,
    Client,
    ClientProfessionRate,
    Department,
    FacilityExperience,
    Profession,
    Site,
)


class Command(BaseCommand):
    help = "Synchronise active locum matching data from the read-only legacy MySQL database."

    def add_arguments(self, parser):
        parser.add_argument(
            "--config",
            default=os.environ.get("LEGACY_MYSQL_CONFIG"),
            help="Path to the protected legacy MySQL JSON connection profile.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Read and count source records without writing to PostgreSQL.",
        )

    def handle(self, *args, **options):
        config_path = options["config"]
        if not config_path:
            raise CommandError(
                "Pass --config or set LEGACY_MYSQL_CONFIG to the protected profile path."
            )

        dataset = self.read_dataset(config_path)
        counts = {name: len(rows) for name, rows in dataset.items()}
        if options["dry_run"]:
            self.stdout.write(
                self.style.WARNING(f"Dry run only; source counts: {counts}")
            )
            return

        imported = self.sync_dataset(dataset)
        self.stdout.write(self.style.SUCCESS(f"Legacy matching data synced: {imported}"))

    def read_dataset(self, config_path):
        try:
            profile = json.loads(Path(config_path).expanduser().read_text())
        except (OSError, ValueError) as exc:
            raise CommandError("Unable to read the protected MySQL profile.") from exc

        try:
            if not isinstance(profile, dict):
                raise TypeError
            host = profile["host"]
            user = profile["user"]
            password = profile["password"]
            database = profile.get("database", "immploy_crm")
            port_value = profile.get("port", 3306)
            if (
                not all(
                    isinstance(value, str) and value.strip()
                    for value in (host, user, password, database)
                )
                or isinstance(port_value, bool)
            ):
                raise TypeError
            port = int(port_value)
            if not 1 <= port <= 65535:
                raise ValueError
        except (KeyError, TypeError, ValueError) as exc:
            raise CommandError("Unable to read the protected MySQL profile.") from exc

        try:
            import mysql.connector
        except ImportError as exc:
            raise CommandError(
                "mysql-connector-python is required for the legacy read-only sync."
            ) from exc

        try:
            connection = mysql.connector.connect(
                host=host,
                port=port,
                user=user,
                password=password,
                database=database,
                connection_timeout=30,
            )
        except mysql.connector.Error as exc:
            raise CommandError(
                "Unable to connect to the legacy database with the protected profile."
            ) from exc

        try:
            cursor = connection.cursor(dictionary=True)
            cursor.execute("SET SESSION TRANSACTION READ ONLY")
            return {
                "departments": self._fetch(cursor, self._departments_sql()),
                "roles": self._fetch(cursor, self._roles_sql()),
                "clients": self._fetch(cursor, self._clients_sql()),
                "client_departments": self._fetch(
                    cursor, self._client_departments_sql()
                ),
                "client_rates": self._fetch(cursor, self._client_rates_sql()),
                "candidate_profile_options": self._fetch(
                    cursor, self._candidate_profile_options_sql()
                ),
                "candidates": self._fetch(cursor, self._candidates_sql()),
                "candidate_departments": self._fetch(
                    cursor, self._candidate_departments_sql()
                ),
                "candidate_roles": self._fetch(cursor, self._candidate_roles_sql()),
                "experiences": self._fetch(cursor, self._experiences_sql()),
            }
        finally:
            connection.close()

    @staticmethod
    def _fetch(cursor, sql):
        cursor.execute(sql)
        return cursor.fetchall()

    @staticmethod
    def _validated_rate(value):
        try:
            rate = Decimal(str(value or 0)).quantize(Decimal("0.01"))
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise CommandError("Legacy rate data is not a valid decimal value.") from exc
        if rate < 0:
            raise CommandError("Legacy rate data cannot contain negative values.")
        return rate

    @staticmethod
    def _legacy_id_list(value):
        ids = []
        for raw_value in str(value or "").split(";"):
            raw_value = raw_value.strip()
            if not raw_value:
                continue
            try:
                ids.append(int(raw_value))
            except ValueError:
                continue
        return list(dict.fromkeys(ids))

    @staticmethod
    def _legacy_date(value):
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        text = str(value or "").strip()
        if len(text) != 10:
            return None
        try:
            return date.fromisoformat(text)
        except ValueError:
            return None

    @transaction.atomic
    def sync_dataset(self, dataset):
        Department.objects.update(is_active=False)
        departments = {}
        for row in dataset.get("departments", []):
            department, _ = Department.objects.update_or_create(
                legacy_mysql_id=row["legacy_id"],
                defaults={"name": row["name"], "is_active": True},
            )
            departments[row["legacy_id"]] = department

        if "candidate_profile_options" in dataset:
            CandidateProfileOption.objects.update(is_active=False)
        profile_options = {}
        for row in dataset.get("candidate_profile_options", []):
            option, _ = CandidateProfileOption.objects.update_or_create(
                category=row["category"],
                legacy_mysql_id=row["legacy_id"],
                defaults={
                    "label": row["label"],
                    "parent_legacy_mysql_id": row.get("parent_id"),
                    "is_active": True,
                },
            )
            profile_options[(row["category"], row["legacy_id"])] = option.label

        def option_label(category, legacy_id):
            if not legacy_id:
                return ""
            return profile_options.get((category, legacy_id), "")

        def option_labels(category, legacy_ids):
            return [
                label
                for legacy_id in self._legacy_id_list(legacy_ids)
                if (label := option_label(category, legacy_id))
            ]

        source_candidate_ids = {
            row["legacy_id"] for row in dataset.get("candidates", [])
        }
        Candidate.objects.filter(legacy_mysql_id__isnull=False).exclude(
            legacy_mysql_id__in=source_candidate_ids
        ).update(
            is_active=False,
            email="",
            phone="",
            identity_number="",
            passport_number="",
            home_phone="",
            other_contact="",
            physical_address="",
            postal_code="",
        )
        Client.objects.filter(legacy_mysql_id__isnull=False).update(is_active=False)
        professions = {}
        for row in dataset["roles"]:
            profession = self._upsert_profession(row)
            professions[row["legacy_id"]] = profession

        clients = {}
        for row in dataset["clients"]:
            client = self._upsert_client(row)
            clients[row["legacy_id"]] = client
            Site.objects.get_or_create(client=client, name="Main facility")
        client_departments = {client_id: [] for client_id in clients}
        for row in dataset.get("client_departments", []):
            department = departments.get(row["department_id"])
            if department and row["client_id"] in client_departments:
                client_departments[row["client_id"]].append(department)
        for legacy_id, client in clients.items():
            client.departments.set(client_departments[legacy_id])

        ClientProfessionRate.objects.filter(
            legacy_mysql_id__isnull=False,
            locally_managed=False,
        ).delete()
        local_rates = {
            (rate.client_id, rate.profession_id): rate
            for rate in ClientProfessionRate.objects.all()
        }
        rates_to_create = []
        rates_to_update = []
        for row in dataset.get("client_rates", []):
            client = clients.get(row["client_id"])
            profession = professions.get(row["role_id"])
            if not client or not profession:
                continue
            pay_rate = self._validated_rate(row["pay_rate"])
            bill_rate = self._validated_rate(row["bill_rate"])
            existing = local_rates.get((client.id, profession.id))
            if existing:
                existing.legacy_mysql_id = row["legacy_id"]
                if not existing.locally_managed:
                    existing.pay_rate = pay_rate
                    existing.bill_rate = bill_rate
                rates_to_update.append(existing)
            else:
                rates_to_create.append(ClientProfessionRate(
                    client=client,
                    profession=profession,
                    legacy_mysql_id=row["legacy_id"],
                    pay_rate=pay_rate,
                    bill_rate=bill_rate,
                ))
        ClientProfessionRate.objects.bulk_create(rates_to_create, batch_size=1000)
        ClientProfessionRate.objects.bulk_update(
            rates_to_update,
            ["legacy_mysql_id", "pay_rate", "bill_rate"],
            batch_size=1000,
        )
        client_rate_count = len(rates_to_create) + len(rates_to_update)

        candidates = {}
        for row in dataset["candidates"]:
            candidate = Candidate.objects.filter(
                legacy_mysql_id=row["legacy_id"],
            ).first()
            if candidate is None:
                candidate = Candidate(legacy_mysql_id=row["legacy_id"])
            source_compliance_status = (
                Candidate.ComplianceStatus.CLEARED
                if row["compliance_code"] == 216
                else Candidate.ComplianceStatus.PENDING
            )
            if not candidate.profile_locally_managed:
                candidate.first_name = row["first_name"] or "Unknown"
                candidate.last_name = row["last_name"] or "Candidate"
                candidate.preferred_name = row.get("preferred_name") or ""
                candidate.date_of_birth = self._legacy_date(row.get("date_of_birth"))
                candidate.identity_number = row.get("identity_number") or ""
                candidate.is_sa_id = bool(row.get("is_sa_id"))
                candidate.passport_number = row.get("passport_number") or ""
                candidate.visa_type = option_label(
                    CandidateProfileOption.Category.VISA_TYPE,
                    row.get("visa_type_id"),
                )
                candidate.visa_start = self._legacy_date(row.get("visa_start"))
                candidate.visa_end = self._legacy_date(row.get("visa_end"))
                candidate.visa_selected = bool(row.get("visa_selected"))
                candidate.country_of_origin = option_label(
                    CandidateProfileOption.Category.COUNTRY,
                    row.get("country_origin_id"),
                )
                candidate.nationality = option_label(
                    CandidateProfileOption.Category.COUNTRY,
                    row.get("nationality_id"),
                )
                candidate.home_language = option_label(
                    CandidateProfileOption.Category.LANGUAGE,
                    row.get("home_language_id"),
                )
                candidate.is_locum = bool(row.get("is_locum"))
                candidate.is_permanent = bool(row.get("is_permanent"))
                candidate.email = row.get("email") or ""
                candidate.phone = row.get("phone") or ""
                candidate.home_phone = row.get("home_phone") or ""
                candidate.other_contact = row.get("other_contact") or ""
                candidate.physical_address = row.get("physical_address") or ""
                candidate.postal_code = row.get("postal_code") or ""
                candidate.note = row.get("note") or ""
                candidate.division = option_label(
                    CandidateProfileOption.Category.DIVISION,
                    row.get("division_id"),
                )
                candidate.assigned_consultant = option_label(
                    CandidateProfileOption.Category.CONSULTANT,
                    row.get("consultant_id"),
                )
                candidate.sex = {
                    6: Candidate.Sex.MALE,
                    7: Candidate.Sex.FEMALE,
                }.get(row.get("sex_id"), "")
                candidate.sex_source = (
                    Candidate.SexSource.LEGACY if candidate.sex else ""
                )
                candidate.employment_equity = option_label(
                    CandidateProfileOption.Category.EMPLOYMENT_EQUITY,
                    row.get("employment_equity_id"),
                )
                candidate.is_disabled = bool(row.get("is_disabled"))
                candidate.drivers_license = option_label(
                    CandidateProfileOption.Category.DRIVERS_LICENSE,
                    row.get("drivers_license_id"),
                )
                candidate.owns_car = bool(row.get("owns_car"))
                candidate.qualification = option_label(
                    CandidateProfileOption.Category.QUALIFICATION,
                    row.get("qualification_id"),
                )
                candidate.qualification_types = option_labels(
                    CandidateProfileOption.Category.QUALIFICATION_TYPE,
                    row.get("qualification_type_ids"),
                )
                candidate.education_level = option_label(
                    CandidateProfileOption.Category.EDUCATION_LEVEL,
                    row.get("education_level_id"),
                )
                candidate.source = option_label(
                    CandidateProfileOption.Category.SOURCE,
                    row.get("source_id"),
                )
                candidate.marital_status = option_label(
                    CandidateProfileOption.Category.MARITAL_STATUS,
                    row.get("marital_status_id"),
                )
                candidate.other_languages = option_labels(
                    CandidateProfileOption.Category.LANGUAGE,
                    row.get("other_language_ids"),
                )
                candidate.home_area = row["home_area"] or ""
                candidate.home_region = canonical_candidate_region(row["home_region"])
                candidate.is_active = True
            candidate.compliance_status = source_compliance_status
            candidate.fingerprint_status = option_label(
                CandidateProfileOption.Category.FINGERPRINT_STATUS,
                row.get("fingerprint_status_id"),
            )
            candidate.criminal_check = option_label(
                CandidateProfileOption.Category.CRIMINAL_CHECK,
                row.get("criminal_check_id"),
            )
            candidate.save()
            candidates[row["legacy_id"]] = candidate

        candidate_departments = {candidate_id: [] for candidate_id in candidates}
        for row in dataset.get("candidate_departments", []):
            department = departments.get(row["department_id"])
            if department and row["candidate_id"] in candidate_departments:
                candidate_departments[row["candidate_id"]].append(department)
        for legacy_id, candidate in candidates.items():
            candidate.departments.set(candidate_departments[legacy_id])

        roles_by_candidate = {candidate_id: [] for candidate_id in candidates}
        for row in dataset["candidate_roles"]:
            profession = professions.get(row["role_id"])
            if profession and row["candidate_id"] in roles_by_candidate:
                roles_by_candidate[row["candidate_id"]].append(profession)
        for legacy_id, candidate in candidates.items():
            if not candidate.profile_locally_managed:
                candidate.professions.set(roles_by_candidate[legacy_id])

        FacilityExperience.objects.filter(
            candidate__legacy_mysql_id__isnull=False
        ).delete()
        aggregated_experiences = {}
        for row in dataset["experiences"]:
            candidate = candidates.get(row["candidate_id"])
            client = clients.get(row["client_id"])
            profession = professions.get(row["role_id"])
            if not all([candidate, client, profession]):
                continue
            key = (candidate.id, client.id, profession.id)
            aggregate = aggregated_experiences.setdefault(
                key,
                {
                    "candidate": candidate,
                    "client": client,
                    "profession": profession,
                    "completed_shift_count": 0,
                    "total_hours": Decimal("0.00"),
                    "last_worked_on": None,
                },
            )
            aggregate["completed_shift_count"] += row["completed_shift_count"]
            aggregate["total_hours"] += Decimal(str(row["total_hours"] or 0))
            if row["last_worked_on"] and (
                aggregate["last_worked_on"] is None
                or row["last_worked_on"] > aggregate["last_worked_on"]
            ):
                aggregate["last_worked_on"] = row["last_worked_on"]

        experiences = [
            FacilityExperience(
                candidate=aggregate["candidate"],
                client=aggregate["client"],
                profession=aggregate["profession"],
                completed_shift_count=aggregate["completed_shift_count"],
                total_hours=aggregate["total_hours"].quantize(Decimal("0.01")),
                last_worked_on=aggregate["last_worked_on"],
            )
            for aggregate in aggregated_experiences.values()
        ]
        FacilityExperience.objects.bulk_create(experiences)

        return {
            "departments": len(departments),
            "roles": len(professions),
            "clients": len(clients),
            "facility_role_rates": client_rate_count,
            "candidate_profile_options": len(profile_options),
            "candidates": len(candidates),
            "role_links": sum(len(roles) for roles in roles_by_candidate.values()),
            "facility_experiences": len(experiences),
        }

    @staticmethod
    def _upsert_profession(row):
        profession = Profession.objects.filter(
            legacy_mysql_id=row["legacy_id"]
        ).first()
        if profession is None:
            profession = Profession.objects.filter(name=row["name"]).first()
        if profession is None:
            profession = Profession(
                name=row["name"],
                legacy_mysql_id=row["legacy_id"],
            )
        elif profession.legacy_mysql_id is None:
            profession.legacy_mysql_id = row["legacy_id"]
        profession.name = row["name"]
        profession.save()
        return profession

    @staticmethod
    def _upsert_client(row):
        client = Client.objects.filter(legacy_mysql_id=row["legacy_id"]).first()
        if client is None:
            client = Client.objects.filter(
                name=row["name"], legacy_mysql_id__isnull=True
            ).order_by("id").first()
        if client is None:
            client = Client(name=row["name"])
        client.legacy_mysql_id = row["legacy_id"]
        client.name = row["name"]
        client.region = row["region"] or ""
        client.city = row["city"] or ""
        client.is_active = True
        client.save()
        return client

    @staticmethod
    def _departments_sql():
        return """
            SELECT desk.no AS legacy_id,
                   desk.desk_name AS name
            FROM tbl_desks desk
            WHERE desk.no IN (1, 2, 3, 5, 9)
            ORDER BY desk.no
        """

    @staticmethod
    def _roles_sql():
        return """
            SELECT DISTINCT role.no AS legacy_id, role.descr AS name
            FROM (
                SELECT modern.no, modern.descr
                FROM tbl_candidates_job_roles modern
                UNION ALL
                SELECT legacy.no, legacy.descr
                FROM tbl_candidates_detail_types_sub_items legacy
            ) role
            JOIN (
                SELECT rates.function_no
                FROM tbl_job_functions_cand_vals rates
                JOIN tbl_candidates candidate ON candidate.no = rates.cand_no
                WHERE rates.is_live = 1
                  AND candidate.dormant = 0
                  AND candidate.is_locum = 1
                UNION
                SELECT client_rate.function_no
                FROM tbl_job_functions_client_vals client_rate
                WHERE client_rate.dormant = 0
                UNION
                SELECT vacancy.function_no
                FROM tbl_vacancy_items item
                JOIN tbl_vacancies vacancy ON vacancy.no = item.vacancy_no
                JOIN tbl_candidates candidate ON candidate.no = item.cand_no
                WHERE item.complete = 1
                  AND item.cancelled_shift = 0
                  AND candidate.dormant = 0
                  AND candidate.is_locum = 1
            ) used_role ON used_role.function_no = role.no
            WHERE role.descr IS NOT NULL AND TRIM(role.descr) <> ''
            ORDER BY role.no
        """

    @staticmethod
    def _clients_sql():
        return """
            SELECT DISTINCT client.no AS legacy_id,
                   client.name,
                   COALESCE(region.descr, '') AS region,
                   COALESCE(city.descr, '') AS city
            FROM tbl_clients client
            JOIN (
                SELECT DISTINCT timesheet.client_no
                FROM tbl_timesheets timesheet
                WHERE timesheet.date_from >= DATE_SUB(CURRENT_DATE, INTERVAL 12 MONTH)
                  AND timesheet.date_from <= CURRENT_DATE
                  AND timesheet.desk IN (1, 2, 3, 5, 9)
            ) recent_timesheet ON recent_timesheet.client_no = client.no
            LEFT JOIN tbl_regions_main region ON region.no = client.region
            LEFT JOIN tbl_regions_city city ON city.no = client.city
            WHERE client.name IS NOT NULL
              AND TRIM(client.name) <> ''
              AND client.dormant = 0
            ORDER BY client.no
        """

    @staticmethod
    def _client_departments_sql():
        return """
            SELECT DISTINCT timesheet.client_no AS client_id,
                   timesheet.desk AS department_id
            FROM tbl_timesheets timesheet
            WHERE timesheet.date_from >= DATE_SUB(CURRENT_DATE, INTERVAL 12 MONTH)
              AND timesheet.date_from <= CURRENT_DATE
              AND timesheet.desk IN (1, 2, 3, 5, 9)
            ORDER BY timesheet.client_no, timesheet.desk
        """

    @staticmethod
    def _client_rates_sql():
        return """
            SELECT rate.no AS legacy_id,
                   rate.client_no AS client_id,
                   rate.function_no AS role_id,
                   ROUND(rate.pay_normal, 2) AS pay_rate,
                   ROUND(rate.normal, 2) AS bill_rate
            FROM tbl_job_functions_client_vals rate
            JOIN (
                SELECT client_no, function_no, MAX(no) AS latest_no
                FROM tbl_job_functions_client_vals
                WHERE dormant = 0
                GROUP BY client_no, function_no
            ) latest ON latest.latest_no = rate.no
            ORDER BY rate.client_no, rate.function_no
        """

    @staticmethod
    def _candidate_profile_options_sql():
        return """
            SELECT 'country' AS category, country.no AS legacy_id,
                   country.descr AS label, NULL AS parent_id
            FROM tbl_job_cj_countries country
            UNION ALL
            SELECT 'visa_type' AS category, visa.no AS legacy_id,
                   visa.descr AS label, NULL AS parent_id
            FROM tbl_visa_types visa
            UNION ALL
            SELECT 'language' AS category, item.no AS legacy_id,
                   item.descr AS label, NULL AS parent_id
            FROM tbl_candidates_detail_types_items item WHERE item.type = 3
            UNION ALL
            SELECT 'division' AS category, desk.no AS legacy_id,
                   desk.desk_name AS label, NULL AS parent_id
            FROM tbl_desks desk
            UNION ALL
            SELECT 'consultant' AS category, consultant.no AS legacy_id,
                   COALESCE(NULLIF(TRIM(CONCAT_WS(' ', consultant.first_name,
                       consultant.last_name)), ''), consultant.username) AS label,
                   NULL AS parent_id
            FROM tbl_users consultant
            WHERE consultant.dormant = 0 AND consultant.assign_cons = 1
            UNION ALL
            SELECT 'gender' AS category, item.no AS legacy_id,
                   item.descr AS label, NULL AS parent_id
            FROM tbl_candidates_detail_types_items item WHERE item.type = 2
            UNION ALL
            SELECT 'employment_equity' AS category, item.no AS legacy_id,
                   item.descr AS label, NULL AS parent_id
            FROM tbl_candidates_detail_types_items item WHERE item.type = 4
            UNION ALL
            SELECT 'education_level' AS category, item.no AS legacy_id,
                   item.descr AS label, NULL AS parent_id
            FROM tbl_candidates_detail_types_items item WHERE item.type = 5
            UNION ALL
            SELECT 'qualification' AS category, item.no AS legacy_id,
                   item.descr AS label, NULL AS parent_id
            FROM tbl_candidates_detail_types_items item WHERE item.type = 6
            UNION ALL
            SELECT 'qualification_type' AS category, subitem.no AS legacy_id,
                   subitem.descr AS label, subitem.type AS parent_id
            FROM tbl_candidates_detail_types_sub_items subitem
            WHERE subitem.type NOT BETWEEN 201 AND 209
            UNION ALL
            SELECT 'source' AS category, item.no AS legacy_id,
                   item.descr AS label, NULL AS parent_id
            FROM tbl_candidates_detail_types_items item WHERE item.type = 7
            UNION ALL
            SELECT 'marital_status' AS category, 1 AS legacy_id,
                   'Single' AS label, NULL AS parent_id
            UNION ALL
            SELECT 'marital_status' AS category, 2 AS legacy_id,
                   'Married' AS label, NULL AS parent_id
            UNION ALL
            SELECT 'drivers_license' AS category, item.no AS legacy_id,
                   item.descr AS label, NULL AS parent_id
            FROM tbl_candidates_detail_types_items item WHERE item.type = 11
            UNION ALL
            SELECT 'fingerprint_status' AS category, item.no AS legacy_id,
                   item.descr AS label, NULL AS parent_id
            FROM tbl_candidates_detail_types_items item WHERE item.type = 16
            UNION ALL
            SELECT 'criminal_check' AS category, item.no AS legacy_id,
                   item.descr AS label, NULL AS parent_id
            FROM tbl_candidates_detail_types_items item WHERE item.type = 17
            UNION ALL
            SELECT 'province' AS category, item.no AS legacy_id,
                   item.descr AS label, NULL AS parent_id
            FROM tbl_candidates_detail_types_items item WHERE item.type = 14
            UNION ALL
            SELECT 'suburb' AS category, subitem.no AS legacy_id,
                   subitem.descr AS label, subitem.type AS parent_id
            FROM tbl_candidates_detail_types_sub_items subitem
            WHERE subitem.type BETWEEN 201 AND 209
            ORDER BY category, label, legacy_id
        """

    @staticmethod
    def _candidates_sql():
        return """
            SELECT candidate.no AS legacy_id,
                   candidate.first_name,
                   candidate.last_name,
                   candidate.prefered_name AS preferred_name,
                   CASE
                       WHEN candidate.DOB IS NULL OR YEAR(candidate.DOB) = 0 THEN NULL
                       ELSE DATE_FORMAT(candidate.DOB, '%Y-%m-%d')
                   END AS date_of_birth,
                   candidate.id_no AS identity_number,
                   candidate.is_sa_id,
                   candidate.passport_no AS passport_number,
                   candidate.visa_type AS visa_type_id,
                   CASE
                       WHEN candidate.visa_start IS NULL OR YEAR(candidate.visa_start) = 0 THEN NULL
                       ELSE DATE_FORMAT(candidate.visa_start, '%Y-%m-%d')
                   END AS visa_start,
                   CASE
                       WHEN candidate.visa_end IS NULL OR YEAR(candidate.visa_end) = 0 THEN NULL
                       ELSE DATE_FORMAT(candidate.visa_end, '%Y-%m-%d')
                   END AS visa_end,
                   candidate.visa_selected,
                   candidate.country_origin AS country_origin_id,
                   candidate.nationality AS nationality_id,
                   candidate.home_lang AS home_language_id,
                   candidate.is_locum,
                   candidate.is_permanent,
                   candidate.email,
                   candidate.cell_no AS phone,
                   candidate.home_tel AS home_phone,
                   candidate.other_contact,
                   candidate.phys_address AS physical_address,
                   candidate.postal_code,
                   candidate.note,
                   candidate.division AS division_id,
                   candidate.assigned_consultant AS consultant_id,
                   candidate.gender AS sex_id,
                   candidate.employment_equity AS employment_equity_id,
                   candidate.disabled AS is_disabled,
                   candidate.fingerprint_status AS fingerprint_status_id,
                   candidate.criminal_check AS criminal_check_id,
                   candidate.drivers_license AS drivers_license_id,
                   candidate.own_car AS owns_car,
                   candidate.qualifications AS qualification_id,
                   candidate.qualification_types AS qualification_type_ids,
                   candidate.edu_level AS education_level_id,
                   candidate.source AS source_id,
                   candidate.marital_status AS marital_status_id,
                   candidate.other_langs AS other_language_ids,
                   COALESCE(area.descr, '') AS home_area,
                   COALESCE(province.descr, '') AS home_region,
                   candidate.compliance AS compliance_code
            FROM tbl_candidates candidate
            JOIN (
                SELECT timesheet.cand_no,
                       MAX(timesheet.date_from) AS max_date
                FROM tbl_timesheets timesheet
                WHERE timesheet.date_from >= '2025-08-01'
                  AND timesheet.date_from <= CURRENT_DATE
                GROUP BY timesheet.cand_no
            ) latest ON latest.cand_no = candidate.no
            LEFT JOIN tbl_candidates_detail_types_sub_items area
                ON area.no = candidate.area
            LEFT JOIN tbl_candidates_detail_types_items province
                ON province.no = candidate.province
            ORDER BY candidate.no
        """

    @staticmethod
    def _candidate_departments_sql():
        return """
            SELECT DISTINCT timesheet.cand_no AS candidate_id,
                   timesheet.desk AS department_id
            FROM tbl_timesheets timesheet
            WHERE timesheet.date_from >= '2025-08-01'
              AND timesheet.date_from <= CURRENT_DATE
              AND timesheet.desk IN (1, 2, 3, 5, 9)
            ORDER BY timesheet.cand_no, timesheet.desk
        """

    @staticmethod
    def _candidate_roles_sql():
        return """
            SELECT rates.cand_no AS candidate_id,
                   rates.function_no AS role_id
            FROM tbl_job_functions_cand_vals rates
            JOIN tbl_candidates candidate ON candidate.no = rates.cand_no
            WHERE rates.is_live = 1
              AND candidate.dormant = 0
              AND candidate.is_locum = 1
            ORDER BY rates.cand_no, rates.function_no
        """

    @staticmethod
    def _experiences_sql():
        return """
            SELECT item.cand_no AS candidate_id,
                   vacancy.client_no AS client_id,
                   vacancy.function_no AS role_id,
                   COUNT(*) AS completed_shift_count,
                   ROUND(SUM(GREATEST(
                       TIMESTAMPDIFF(MINUTE, item.start_time, item.end_time), 0
                   )) / 60, 2) AS total_hours,
                   MAX(item.date) AS last_worked_on
            FROM tbl_vacancy_items item
            JOIN tbl_vacancies vacancy ON vacancy.no = item.vacancy_no
            JOIN tbl_candidates candidate ON candidate.no = item.cand_no
            WHERE item.complete = 1
              AND item.cancelled_shift = 0
              AND item.date <= CURRENT_DATE
              AND candidate.dormant = 0
              AND candidate.is_locum = 1
            GROUP BY item.cand_no, vacancy.client_no, vacancy.function_no
            ORDER BY item.cand_no, vacancy.client_no, vacancy.function_no
        """
