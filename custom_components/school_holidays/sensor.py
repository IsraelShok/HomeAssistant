"""
Platform to get if is school vaction for Home Assistant.

Document will come soon...
"""
import logging
import codecs
import datetime
import json
import pathlib
import aiohttp
import voluptuous as vol
from homeassistant.components.sensor import PLATFORM_SCHEMA
import homeassistant.helpers.config_validation as cv
from homeassistant.const import (CONF_RESOURCES)
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity import async_generate_entity_id
from homeassistant.components.sensor import ENTITY_ID_FORMAT

__version__ = '2.0.1'

_LOGGER = logging.getLogger(__name__)

SENSOR_PREFIX = 'School '
ELEMENTARY_SCHOOL = 'elementary_school'
HIGH_SCHOOL = 'high_school'

SENSOR_TYPES = {
    'is_high_vacation': ['mdi:school', 'is_high_vacation'],
    'is_elementary_vacation': ['mdi:school', 'is_elementary_vacation'],
    'summary': ['mdi:rename-box', 'summary'],
}

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Required(ELEMENTARY_SCHOOL): cv.string,
    vol.Required(HIGH_SCHOOL): cv.string,
    vol.Required(CONF_RESOURCES, default=[]):
        vol.All(cv.ensure_list, [vol.In(SENSOR_TYPES)]),
})


async def async_setup_platform(
        hass, config, async_add_entities, discovery_info=None):
    """Setup the shabbat config sensors."""
    elementary_school = config.get(ELEMENTARY_SCHOOL)
    high_school = config.get(HIGH_SCHOOL)
    entities = []

    for resource in config[CONF_RESOURCES]:
        sensor_type = resource.lower()
        if sensor_type not in SENSOR_TYPES:
            SENSOR_TYPES[sensor_type] = [
                sensor_type.title(), '', 'mdi:flash']
        entities.append(SchoolHolidays(hass, sensor_type, elementary_school, high_school))
    async_add_entities(entities, False)


# pylint: disable=abstract-method

async def fetch(session, url):
    async with session.get(url) as response:
        return await response.text()


class SchoolHolidays(Entity):
    """Representation of a israel school vaction."""
    school_db = []
    version_db = []
    summary_name = None
    config_path = None

    def __init__(self, hass, sensor_type, elementary_school, high_school):
        """Initialize the sensor."""
        self.type = sensor_type
        self.config_path = hass.config.path() + "/custom_components/school_holidays/"
        self.elementary_school = elementary_school
        self.high_school = high_school
        self.entity_id = async_generate_entity_id(
            ENTITY_ID_FORMAT,
            '_'.join([SENSOR_PREFIX, SENSOR_TYPES[self.type][1]]), hass=hass)
        self._state = None
        self._summary_name = None
        self._elementary_school_status = None
        self._high_school_status = None
        self.create_db_file()

    @property
    def name(self):
        """Return the name of the sensor."""
        return SENSOR_PREFIX + SENSOR_TYPES[self.type][1]

    @property
    def icon(self):
        """Icon to use in the frontend, if any."""
        return SENSOR_TYPES[self.type][0]

    @property
    def state(self):
        """Return the state of the sensor."""
        return self._state

    async def async_update(self):
        """Update our sensor state."""
        if self.school_db:
            await self.is_vacation()
            type_to_func = {
                'is_high_vacation': self.get_high_school_status,
                'is_elementary_vacation': self.get_elementary_school_status,
                'summary': self.get_summary_name,
            }
            self._state = await type_to_func[self.type]()
            await self.async_update_ha_state()
        else:
            await self.create_db_file()

    async def create_db_file(self):
        """Create the json db."""
        try:
            async with aiohttp.ClientSession() as session:
                html = await fetch(session,
                                   'https://raw.githubusercontent.com/rt400/School-Vacation/master/data.json')
                data = json.loads(html)
                with codecs.open(self.config_path + 'school_data.json', 'w', encoding='utf-8') as outfile:
                    json.dump(data, outfile, skipkeys=False, ensure_ascii=False,
                              indent=4, separators=None, default=None, sort_keys=True)
            self.school_db = data
        except Exception as e:
            _LOGGER.error(e)

    async def is_vacation(self):
        """Check if it is school day."""
        now = datetime.date.today()
        if now.isoweekday() != 6:
            for extract_data in self.school_db:
                if "HIGH" in extract_data.values():
                    start = datetime.datetime.strptime(str(extract_data['START']), '%Y%m%d').date()
                    end = datetime.datetime.strptime(str(extract_data['END']), '%Y%m%d').date()
                    if start == now < end:
                        self._summary_name = "חופש גדול - על יסודי"
                        self._high_school_status = "True"
                        self._elementary_school_status = "False"
                        return True
                else:
                    start = datetime.datetime.strptime(str(extract_data['START']), '%Y%m%d').date()
                    end = datetime.datetime.strptime(str(extract_data['END']), '%Y%m%d').date()
                    if start == now < end:
                        self._summary_name = str(extract_data['SUMMARY'])
                        self._high_school_status = "True"
                        self._elementary_school_status = "True"
                        return True
        elif now.isoweekday() == 6:
            self._summary_name = "יום שבת"
            self._high_school_status = "True"
            self._elementary_school_status = "True"
            return True
        if self.elementary_school.__eq__("True") and now.isoweekday() == 5:
            self._high_school_status = "True"
            self._elementary_school_status = "False"
            self._summary_name = "אין לימודים - על יסודי"
            return True
        self._high_school_status = "False"
        self._elementary_school_status = "False"
        self._summary_name = "יום לימודים"

    async def get_summary_name(self):
        """Return the state of the sensor."""
        if self._summary_name is None:
            self._summary_name = "Error"
        return str(self._summary_name)

    async def get_elementary_school_status(self):
        """Return the state of the sensor."""
        if self._elementary_school_status is None:
            self._elementary_school_status = "Error"
        return str(self._elementary_school_status)

    async def get_high_school_status(self):
        """Return the state of the sensor."""
        if self._high_school_status is None:
            self._high_school_status = "Error"
        return str(self._high_school_status)
