from datetime import date

from world_check_mcp.contexts.passport.errors import PassportError
from world_check_mcp.contexts.passport.models import Mrz
from world_check_mcp.contexts.passport.models import Passport
from world_check_mcp.upstream import GET_MRZ
from world_check_mcp.upstream import GET_NATIONALITIES
from world_check_mcp.upstream import Upstream


async def generate_passport_mrz(*, upstream: Upstream, passport: Passport) -> Mrz:
    """MRZ lines for a document. This does not create a case or record a verification."""
    if passport.date_of_birth > date.today():
        raise PassportError("Date of birth cannot be in the future.")
    nationalities = (await upstream.call(GET_NATIONALITIES)).root
    issuing_state = passport.issuing_state.upper()
    nationality = passport.nationality.upper()
    if issuing_state not in nationalities or nationality not in nationalities:
        raise PassportError(
            "Use issuing-state and nationality codes from get_reference_data nationalities, "
            "not the WATCHLIST country list."
        )
    generated = await upstream.call(
        GET_MRZ,
        givenName=passport.given_name,
        lastName=passport.last_name,
        gender=passport.gender,
        dateOfBirth=passport.date_of_birth.isoformat(),
        issuingState=issuing_state,
        nationality=nationality,
        identificationNumber=passport.identification_number,
        dateOfExpiry=passport.date_of_expiry.isoformat(),
        documentType=passport.document_type,
    )
    if not generated.lines:
        raise PassportError("LSEG returned no MRZ lines.")
    return Mrz(lines=generated.lines, conforms_with_icao=generated.conforms_with_icao)
