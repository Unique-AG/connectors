from office_365_mcp.shared.identity import member_in_question, person_in_question
from office_365_mcp.shared.prose import PREVIEW_CHARACTERS

_JANE_ID = "00000000-0000-4000-8000-000000000003"


class TestPersonInQuestion:
    def test_it_shows_the_object_id_first_and_the_name_as_a_label_from_the_request(self) -> None:
        assert person_in_question(_JANE_ID, "Jane Smith") == (
            "the person with the Microsoft Entra object id "
            + "'00000000-0000-4000-8000-000000000003' (the name 'Jane Smith' is only a label from "
            + "the request)"
        )

    def test_a_name_of_another_person_still_shows_the_object_id_that_graph_binds(self) -> None:
        shown = person_in_question(_JANE_ID, "Grace Hopper")

        assert _JANE_ID in shown
        assert "'Grace Hopper' is only a label from the request" in shown

    def test_a_long_name_is_cut_and_the_object_id_is_kept(self) -> None:
        shown = person_in_question(_JANE_ID, "G" * (PREVIEW_CHARACTERS + 1))

        assert _JANE_ID in shown
        assert f"'{'G' * PREVIEW_CHARACTERS}…'" in shown
        assert "G" * (PREVIEW_CHARACTERS + 1) not in shown


class TestMemberInQuestion:
    def test_it_shows_the_object_id_first_and_the_name_from_microsoft_365(self) -> None:
        assert member_in_question(_JANE_ID, "Jane Smith") == (
            "the person with the Microsoft Entra object id "
            + "'00000000-0000-4000-8000-000000000003' (the name 'Jane Smith' comes from "
            + "Microsoft 365)"
        )

    def test_a_long_name_is_cut_and_the_object_id_is_kept(self) -> None:
        shown = member_in_question(_JANE_ID, "J" * (PREVIEW_CHARACTERS + 1))

        assert _JANE_ID in shown
        assert f"'{'J' * PREVIEW_CHARACTERS}…'" in shown
