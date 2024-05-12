"""Data update coordinator for the Ecole Directe integration."""

from __future__ import annotations

import datetime
import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import TimestampDataUpdateCoordinator

from .ecole_directe_formatter import format_grade

from .ecole_directe_helper import (
    EDEleve,
    EDGrade,
    EDLesson,
    get_ecoledirecte_session,
    get_homeworks,
    get_grades,
    get_homeworks_by_date,
    get_lessons
)

from .const import (
    DEFAULT_REFRESH_INTERVAL,
    EVENT_TYPE,
)

_LOGGER = logging.getLogger(__name__)


class EDDataUpdateCoordinator(TimestampDataUpdateCoordinator):
    """Data update coordinator for the Ecole Directe integration."""

    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass=hass,
            logger=_LOGGER,
            name=entry.title,
            update_interval=timedelta(
                minutes=entry.options.get("refresh_interval", DEFAULT_REFRESH_INTERVAL)
            ),
        )
        self.config_entry = entry

    async def _async_update_data(self) -> dict[Platform, dict[str, Any]]:
        """Get the latest data from Ecole Directe and updates the state."""

        previous_data = None if self.data is None else self.data.copy()

        data = self.config_entry.data

        session = await self.hass.async_add_executor_job(
            get_ecoledirecte_session, data, self.hass.config.config_dir, self.hass
        )

        if session is None:
            _LOGGER.error("Unable to init ecole directe client")
            return None

        self.data = {}
        self.data["session"] = session

        current_year = datetime.datetime.now().year
        if (current_year % 2) == 0:
            year_data = f"{str(current_year-1)}-{str(current_year)}"
        else:
            year_data = f"{str(current_year)}-{str(current_year + 1)}"

        #EDT BODY
        edt_date_start = "2024-05-02"
        edt_date_end = "2024-05-03"

        # if session._account_type == "1":  # famille
        #     if "MESSAGERIE" in session.modules:
        #         try:
        #             self.data["messages"] = await self.hass.async_add_executor_job(
        #                 get_messages, session, None, year_data
        #             )
        #         except Exception as ex:
        #             _LOGGER.warning(
        #                 "Error getting messages for family from ecole directe: %s", ex
        #             )

        for eleve in session.eleves:
            if "CAHIER_DE_TEXTES" in eleve.modules:
                try:
                    self.data[
                        f"{eleve.get_fullname_lower()}_homework"
                    ] = await self.hass.async_add_executor_job(
                        get_homeworks, session.token, eleve, self.hass.config.config_dir
                    )
                except Exception as ex:
                    _LOGGER.warning(
                        "Error getting homeworks from ecole directe: %s", ex
                    )
            if "NOTES" in eleve.modules:
                try:
                    self.data[
                        f"{eleve.get_fullname_lower()}_grades"
                    ] = await self.hass.async_add_executor_job(
                        get_grades,
                        session.token,
                        eleve,
                        year_data,
                        self.hass.config.config_dir,
                    )
                    self.compare_data(
                        previous_data,
                        f"{eleve.get_fullname_lower()}_grades",
                        ["date", "subject", "grade_out_of"],
                        "new_grade",
                        eleve,
                        format_grade,
                    )
                except Exception as ex:
                    _LOGGER.warning("Error getting grades from ecole directe: %s", ex)
            
            if "EDT" in eleve.modules:
                try:
                    self.data[
                        f"{eleve.get_fullname_lower()}_lessons"
                    ] = await self.hass.async_add_executor_job(
                        get_lessons, session.token, eleve, edt_date_start, edt_date_end 
                    )
                    
                except Exception as ex:
                    _LOGGER.warning("Error getting Lessons  from ecole directe: %s", ex)
            
            # if "MESSAGERIE" in eleve.modules:
            #     try:
            #         self.data[
            #             "messages" + eleve.eleve_id
            #         ] = await self.hass.async_add_executor_job(
            #             get_messages, session, eleve, year_data
            #         )
            #     except Exception as ex:
            #         _LOGGER.warning("Error getting messages from ecole directe: %s", ex)

            # fake event new_grade
            # grade = EDGrade(
            #     data={
            #         "codeMatiere": "FRANC",
            #         "codePeriode": "A001",
            #         "codeSousMatiere": "",
            #         "coef": "1",
            #         "commentaire": "",
            #         "date": "2023-09-23",
            #         "dateSaisie": "2023-10-04",
            #         "devoir": "Rédaction : randonnée de début d'année",
            #         "enLettre": False,
            #         "id": 8388851,
            #         "libelleMatiere": "FRANCAIS",
            #         "moyenneClasse": "12.61",
            #         "nonSignificatif": False,
            #         "noteSur": "20",
            #         "typeDevoir": "ECRIT",
            #         "uncCorrige": "",
            #         "uncSujet": "",
            #         "valeur": "14,5",
            #         "valeurisee": False,
            #     }
            # )
            # self.trigger_event(
            #     "new_grade",
            #     eleve,
            #     format_grade(grade),
            # )

        return self.data

    def compare_data(
        self,
        previous_data,
        data_key,
        compare_keys,
        event_type,
        eleve: EDEleve,
        format_func,
    ):
        """Compare data from previous session"""

        try:
            if (
                previous_data is not None
                and data_key in previous_data
                and data_key in self.data
            ):
                not_found_items = []
                for item in self.data[data_key]:
                    found = False
                    for previous_item in previous_data[data_key]:
                        if {
                            key: format_func(previous_item)[key] for key in compare_keys
                        } == {key: format_func(item)[key] for key in compare_keys}:
                            found = True
                            break
                    if found is False:
                        not_found_items.append(item)
                for not_found_item in not_found_items:
                    self.trigger_event(event_type, eleve, format_func(not_found_item))
        except Exception as ex:
            _LOGGER.warning(
                "Error comparing data: self[%s] previous_data[%s] data_key[%s] ex[%s]",
                self,
                previous_data,
                data_key,
                ex,
            )

    def trigger_event(self, event_type, eleve: EDEleve, event_data):
        """Trigger an event if there is new data"""

        event_data = {
            "child_name": eleve.get_fullname(),
            "type": event_type,
            "data": event_data,
        }
        self.hass.bus.fire(EVENT_TYPE, event_data)
