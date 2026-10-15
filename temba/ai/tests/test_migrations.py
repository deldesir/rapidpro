from temba.tests import MigrationTest


class SplitEngineRoleTest(MigrationTest):
    app = "ai"
    migrate_from = "0013_alter_llm_id"
    migrate_to = "0014_split_engine_role"

    def setUpBeforeMigration(self, apps):
        LLM = apps.get_model("ai", "LLM")

        def create_llm(name: str, roles: str):
            return LLM.objects.create(
                org_id=self.org.id,
                name=name,
                llm_type="openai",
                model="gpt-5.4-mini",
                config={},
                roles=roles,
                created_by_id=self.admin.id,
                modified_by_id=self.admin.id,
            )

        self.llm1 = create_llm("Both", "TF")
        self.llm2 = create_llm("Editing", "T")
        self.llm3 = create_llm("Engine", "F")

    def test_migration(self):
        def assert_roles(llm, roles: str):
            llm.refresh_from_db()
            self.assertEqual(roles, llm.roles)

        assert_roles(self.llm1, "TGC")
        assert_roles(self.llm2, "T")
        assert_roles(self.llm3, "GC")
