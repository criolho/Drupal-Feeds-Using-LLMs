from typing import Optional  # For optional type hints
from pydantic_settings import BaseSettings  # Settings management with validation
from dotenv import load_dotenv

# Load environment variables from .env file if present
load_dotenv()


class AgencySettings(BaseSettings):
    """
    Base settings class for all federal agencies.
    """

    name: str = ""
    description: str = ""
    fr_agency_name: str = ""
    short_name: str = ""
    federal_register_url: str = "https://www.federalregister.gov/api/v1/documents.json?fields[]=type&fields[]=publication_date&fields[]=abstract&fields[]=agency_names&fields[]=citation&fields[]=effective_on&fields[]=document_number&fields[]=pdf_url&fields[]=body_html_url&fields[]=title&conditions[publication_date][gte]=DATE_PLACEHOLDER&conditions[agencies][]=FR_AGENCY_NAME&conditions[type][]=RULE&conditions[type][]=PRORULE"


class HHS(AgencySettings):
    name: str = "Health and Human Services Department"
    description: str = "HHS is the Cabinet-level department of the Federal executive branch most involved with the Nation's human concerns. In one way or another, it touches the lives of more Americans than any other Federal agency. It is a department of people serving people, from newborn infants to persons requiring health services to our most elderly citizens."
    fr_agency_name: str = "health-and-human-services-department"
    short_name: str = "hhs"


class DOT(AgencySettings):
    name: str = "Department of Transportation"
    description: str = "Federal department responsible for transportation regulations"
    fr_agency_name: str = "transportation-department"
    short_name: str = "dot"


class EPA(AgencySettings):
    name: str = "Environmental Protection Agency"
    description: str = (
        "Federal agency responsible for environmental protection and regulations"
    )
    fr_agency_name: str = "environmental-protection-agency"
    short_name: str = "epa"


class FMSC(AgencySettings):
    name: str = "Federal Mine Safety and Health Review Commission"
    description: str = "The Federal Mine Safety and Health Review Commission ensures compliance with occupational safety and health standards in the Nation's surface and underground coal, metal, and nonmetal mines."
    fr_agency_name: str = "federal-mine-safety-and-health-review-commission"
    short_name: str = "fmsc"


class NOAA(AgencySettings):
    name: str = "National Oceanic and Atmospheric Administration"
    description: str = "Federal department responsible for protecting America's ocean, coastal, and living marine resources while promoting sustainable economic development."
    fr_agency_name: str = "national-oceanic-and-atmospheric-administration"
    short_name: str = "noaa"

class USCIS(AgencySettings):
    name: str = "U.S. Citizenship and Immigration Services"
    description: str = "Immigration and Customs Enforcement (ICE) and Customs and Border Protection (CBP), components within DHS, handle immigration enforcement and border security functions."
    fr_agency_name: str = "u-s-citizenship-and-immigration-services"
    short_name: str = "uscis"

class NHTSA(AgencySettings):
    name: str = "National Highway Traffic Safety Administration"
    description: str = "NHTSA carries out programs relating to the safety performance of motor vehicles and related equipment; administers the State and community highway safety program with the FHWA; regulates the Corporate Average Fuel Economy program; investigates and prosecutes odometer fraud; carries out the National Driver Register Program to facilitate the exchange of State records on problem drivers; conducts studies and operates programs aimed at reducing economic losses in motor vehicle crashes and repairs; performs studies, conducts demonstration projects, and promotes programs to reduce impaired driving, increase seat belt use, and reduce risky driver behaviors; and issues theft prevention standards for passenger and nonpassenger motor vehicles."
    fr_agency_name: str = "national-highway-traffic-safety-administration"
    short_name: str = "nhtsa"


class Settings(BaseSettings):
    """
    Main settings class that aggregates all agency-specific settings.
    """

    dot: DOT = DOT()
    epa: EPA = EPA()
    fmsc: FMSC = FMSC()
    hhs: HHS = HHS()
    noaa: NOAA = NOAA()
    nhtsa: NHTSA = NHTSA()
    uscis: USCIS = USCIS()

    # Function to get agency by name
    def get_agency_by_name(self, agency_name: str) -> Optional[AgencySettings]:
        """
        Get agency settings by either FR agency name or short name

        Args:
            agency_name: The agency name to look up (can be FR name or short name)

        Returns:
            AgencySettings or None: The settings for the specified agency, or None if not found
        """

        """
        Build agency_map dynamically by iterating through the attributes
        of the Settings class, checking if an attribute is an instance
        of AgencySettings, and if so, adding both fr_agency_name and
        short_name (in lowercase) as keys to the agency_map pointing to
        the AgencySettings object.
        """
        agency_map = {}

        """
        self.__dict__ is a dictionary that holds the instance's
        attributes. For a Settings instance, this will contain attributes
        like hhs, dot, epa, etc., which are the AgencySettings instances.

        self.__dict__.values() gives us an iterable of the values in
        this dictionary. We are directly iterating over the HHS(), DOT(),
        EPA() instances themselves, rather than attribute names.

        isinstance(agency_setting, AgencySettings): We check
        if the current agency_setting (which is a value from
        self.__dict__.values()) is an instance of AgencySettings. This
        ensures we only process the agency setting objects.
        """
        for (
            agency_setting
        ) in self.__dict__.values():  # Iterate over values in instance __dict__
            if isinstance(agency_setting, AgencySettings):
                agency_map[agency_setting.fr_agency_name.lower()] = agency_setting
                agency_map[agency_setting.short_name.lower()] = agency_setting

        """
        Example format:
        agency_map = {
            self.epa.fr_agency_name: self.epa,
            self.epa.short_name: self.epa,
            self.hhs.fr_agency_name: self.hhs,
            self.hhs.short_name: self.hhs,
        }
        """
        return agency_map.get(agency_name.lower())


def get_settings():
    """
    Return a Settings instance.

    Returns:
        Settings: Configured settings object with all provider settings
    """
    return Settings()
