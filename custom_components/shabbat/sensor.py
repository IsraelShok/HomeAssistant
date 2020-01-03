"""
Platform to get Shabbath Times And Shabbath information for Home Assistant.

Document will come soon...
"""
import logging
import urllib
import json
import codecs
import pathlib
import datetime
import time
import voluptuous as vol
from homeassistant.components.sensor import PLATFORM_SCHEMA
import homeassistant.helpers.config_validation as cv
from homeassistant.const import (
    CONF_LATITUDE, CONF_LONGITUDE, CONF_RESOURCES)
from homeassistant.helpers.entity import Entity
from homeassistant.core import callback
from homeassistant.helpers.entity import async_generate_entity_id
from homeassistant.components.sensor import ENTITY_ID_FORMAT

_LOGGER = logging.getLogger(__name__)

SENSOR_PREFIX = 'Shabbat '
HAVDALAH_MINUTES = 'havdalah_calc'
TIME_BEFORE_CHECK = 'time_before_check'
TIME_AFTER_CHECK = 'time_after_check'

SENSOR_TYPES = {
    'in': ['כניסת שבת', 'mdi:candle', 'in'],
    'out': ['צאת שבת', 'mdi:exit-to-app', 'out'],
    'is_shabbat': ['IN', 'mdi:candle', 'is_shabbat'],
    'parasha': ['פרשת השבוע', 'mdi:book-open-variant', 'parasha'],
    'hebrew_date': ['תאריך עברי', 'mdi:calendar', 'hebrew_date'],
}

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Optional(CONF_LATITUDE): cv.latitude,
    vol.Optional(CONF_LONGITUDE): cv.longitude,
    vol.Optional(HAVDALAH_MINUTES, default=42): int,
    vol.Optional(TIME_BEFORE_CHECK, default=10): int,
    vol.Optional(TIME_AFTER_CHECK, default=10): int,
    vol.Required(CONF_RESOURCES, default=[]):
        vol.All(cv.ensure_list, [vol.In(SENSOR_TYPES)]),
})


async def async_setup_platform(
        hass, config, async_add_entities, discovery_info=None):
    """Set up the shabbat config sensors."""
    havdalah = config.get(HAVDALAH_MINUTES)
    latitude = config.get(CONF_LATITUDE, hass.config.latitude)
    longitude = config.get(CONF_LONGITUDE, hass.config.longitude)
    time_before = config.get(TIME_BEFORE_CHECK)
    time_after = config.get(TIME_AFTER_CHECK)

    if None in (latitude, longitude):
        _LOGGER.error("Latitude or longitude not set in Home Assistant config")
        return

    entities = []

    for resource in config[CONF_RESOURCES]:
        sensor_type = resource.lower()
        if sensor_type not in SENSOR_TYPES:
            SENSOR_TYPES[sensor_type] = [
                sensor_type.title(), '', 'mdi:flash']
        entities.append(Shabbat(hass, sensor_type, hass.config.time_zone, latitude, longitude,
                                havdalah, time_before, time_after))
    async_add_entities(entities, False)


class Shabbat(Entity):
    """Create shabbat sensor."""
    shabbat_db = []
    hebrew_date_db = None
    shabbatin = None
    shabbatout = None
    file_time_stamp = None
    friday = None
    saturday = None
    config_path = None

    def __init__(self, hass, sensor_type, timezone, latitude, longitude,
                 havdalah, time_before, time_after):
        """Initialize the sensor."""
        self.type = sensor_type
        self.entity_id = async_generate_entity_id(
            ENTITY_ID_FORMAT,
            '_'.join([SENSOR_PREFIX, SENSOR_TYPES[self.type][2]]), hass=hass)
        self._latitude = latitude
        self._longitude = longitude
        self._timezone = timezone
        self._havdalah = havdalah
        self._time_before = time_before
        self._time_after = time_after
        self.config_path = hass.config.path() + "/custom_components/shabbat/"
        self._state = None
        # async_track_time_interval(
        #     hass, self.async_update, datetime.timedelta(days=1))

    @property
    def name(self):
        """Return the name of the sensor."""
        return SENSOR_PREFIX + SENSOR_TYPES[self.type][2]

    @property
    def icon(self):
        """Icon to use in the frontend, if any."""
        return SENSOR_TYPES[self.type][1]

    @property
    def should_poll(self):
        """Return true if the device should be polled for state updates"""
        return True

    @property
    def state(self):
        """Return the state of the sensor."""
        return self._state

    async def async_update(self):
        """Update our sensor state."""
        await self.update_db()
        type_to_func = {
            'in': self.get_time_in,
            'out': self.get_time_out,
            'is_shabbat': self.is_shabbat,
            'parasha': self.get_parasha,
            'hebrew_date': self.get_hebrew_date
        }
        self._state = await type_to_func[self.type]()

        await self.async_update_ha_state()

    async def create_db_file(self):
        """Create the json db."""
        self.set_days()
        self.shabbat_db = []
        self.file_time_stamp = datetime.date.today()
        convert = {"date": str(self.file_time_stamp)}
        with codecs.open(self.config_path + 'date_update.json', 'w', encoding='utf-8') as outfile:
            json.dump(convert, outfile, skipkeys=False, ensure_ascii=False, indent=4,
                      separators=None, default=None, sort_keys=True)

        try:
            with urllib.request.urlopen(
                    "https://www.hebcal.com/hebcal/?v=1&cfg=fc&start="
                    + str(self.friday) + "&end=" + str(self.saturday)
                    + "&ss=on&c=on&geo=pos&latitude=" + str(self._latitude)
                    + "&longitude=" + str(self._longitude)
                    + "&tzid=" + str(self._timezone)
                    + "&m=" + str(self._havdalah) + "&s=on"
            ) as shabbat_url:
                temp_db = json.loads(shabbat_url.read().decode())
            for extract_data in temp_db:
                if "candles" in extract_data.values():
                    day = datetime.datetime.strptime(extract_data['start'], '%Y-%m-%dT%H:%M:%S').isoweekday()
                    if day is 5:
                        self.shabbat_db.append(extract_data)
                    elif day is 6:
                        havdalah_time = str(datetime.datetime.strptime(extract_data['start'], '%Y-%m-%dT%H:%M:%S')
                                            + datetime.timedelta(minutes=5)
                                            + datetime.timedelta(days=1)).replace(" ", "T")
                        self.shabbat_db.append(
                            {'hebrew': 'הבדלה - 42 דקות', 'start': havdalah_time, 'className': 'havdalah',
                             'allDay': False, 'title': 'הבדלה - 42 דקות'})
                else:
                    self.shabbat_db.append(extract_data)
            with codecs.open(self.config_path + 'shabbat_data.json', 'w', encoding='utf-8') as outfile:
                json.dump(self.shabbat_db, outfile, skipkeys=False, ensure_ascii=False, indent=4,
                          separators=None, default=None, sort_keys=True)
        except:
            self.shabbat_db = self.shabbat_db

        try:
            with urllib.request.urlopen(
                    "https://www.hebcal.com/converter/?cfg=json&gy="
                    + str(datetime.date.today().year) + "&gm=" + str(datetime.date.today().month)
                    + "&gd=" + str(datetime.date.today().day) + "&g2h=1"
            ) as heb_url:
                self.hebrew_date_db = json.loads(heb_url.read().decode())
            with codecs.open(self.config_path + 'hebdate_data.json', 'w', encoding='utf-8') as outfile:
                json.dump(self.hebrew_date_db, outfile, skipkeys=False, ensure_ascii=False, indent=4,
                          separators=None, default=None, sort_keys=True)
        except:
            self.hebrew_date_db = self.hebrew_date_db

    async def update_db(self):
        """Update the db."""
        if not pathlib.Path(self.config_path + 'shabbat_data.json').is_file() or \
                not pathlib.Path(self.config_path + 'hebdate_data.json').is_file() or \
                not pathlib.Path(self.config_path + 'date_update.json').is_file():
            await self.create_db_file()
        elif not self.shabbat_db or self.hebrew_date_db is None or self.file_time_stamp is None:
            with open(self.config_path + 'shabbat_data.json', encoding='utf-8') as data_file:
                self.shabbat_db = json.loads(data_file.read())
            with open(self.config_path + 'hebdate_data.json', encoding='utf-8') as hebdata_file:
                self.hebrew_date_db = json.loads(hebdata_file.read())
            with open(self.config_path + 'date_update.json', encoding='utf-8') as data_file:
                data = json.loads(data_file.read())
                self.file_time_stamp = datetime.datetime.strptime(
                    data['date'], '%Y-%m-%d').date()
        elif self.file_time_stamp != datetime.date.today():
            await self.create_db_file()
        await self.get_full_time_in()
        await self.get_full_time_out()

    @callback
    def set_days(self):
        """Set the friday and saturday."""
        weekday = self.set_friday(datetime.date.today().isoweekday())
        self.friday = datetime.date.today() + datetime.timedelta(days=weekday)
        self.saturday = datetime.date.today() + datetime.timedelta(
            days=weekday + 1)

    @classmethod
    def set_friday(cls, day):
        """Set friday day."""
        switcher = {
            7: 5,
            1: 4,
            2: 3,
            3: 2,
            4: 1,
            5: 0,
            6: -1,
        }
        return switcher.get(day)

    # get shabbat entrace
    async def get_time_in(self):
        """Get shabbat entrace."""
        result = ''
        for extract_data in self.shabbat_db:
            if "candles" in extract_data.values():
                result = extract_data['start'][11:16]
        if self.is_time_format(result):
            return result
        return 'Error'

    # get shabbat time exit
    async def get_time_out(self):
        """Get shabbat time exit."""
        result = ''
        for extract_data in self.shabbat_db:
            if "havdalah" in extract_data.values():
                result = extract_data['start'][11:16]
        if self.is_time_format(result):
            return result
        return 'Error'

    # get full time entrace shabbat for check if is shabbat now
    async def get_full_time_in(self):
        """Get full time entrace shabbat for check if is shabbat now."""
        for extract_data in self.shabbat_db:
            if "candles" in extract_data.values():
                self.shabbatin = extract_data['start']
        if self.shabbatin is not None:
            self.shabbatin = self.shabbatin

    # get full time exit shabbat for check if is shabbat now
    async def get_full_time_out(self):
        """Get full time exit shabbat for check if is shabbat now."""
        for extract_data in self.shabbat_db:
            if "havdalah" in extract_data.values():
                self.shabbatout = extract_data['start']
        if self.shabbatout is not None:
            self.shabbatout = self.shabbatout

    # get parashat hashavo'h
    async def get_parasha(self):
        """Get parashat hashavo'h."""
        result = 'שבת מיוחדת'
        get_shabbat_name = None
        for extract_data in self.shabbat_db:
            if "parashat" in extract_data.values():
                result = extract_data['hebrew']
            for data in extract_data.keys():
                if data == 'subcat' and extract_data[data] == 'shabbat':
                    get_shabbat_name = extract_data
        if get_shabbat_name is not None:
            result = result + ' - ' + get_shabbat_name['hebrew']
        return result

    # check if is shabbat now / return true or false
    async def is_shabbat(self):
        """Check if is shabbat now / return true or false."""
        if self.shabbatin is not None and self.shabbatout is not None:
            is_in = datetime.datetime.strptime(
                self.shabbatin, '%Y-%m-%dT%H:%M:%S')
            is_out = datetime.datetime.strptime(
                self.shabbatout, '%Y-%m-%dT%H:%M:%S')
            is_in = is_in - datetime.timedelta(
                minutes=int(self._time_before))
            is_out = is_out + datetime.timedelta(
                minutes=int(self._time_after))
            if (is_in.replace(tzinfo=None) <
                    datetime.datetime.today() < is_out.replace(tzinfo=None)):
                return 'True'
            return 'False'
        return 'False'

    # convert to hebrew date
    async def get_hebrew_date(self):
        """Convert to hebrew date."""
        day = self.heb_day_str()
        return day + self.hebrew_date_db['hebrew']

    @classmethod
    def heb_day_str(cls):
        """Set hebrew day."""
        switcher = {
            7: "יום ראשון, ",
            1: "יום שני, ",
            2: "יום שלישי, ",
            3: "יום רביעי, ",
            4: "יום חמישי, ",
            5: "יום שישי, ",
            6: "יום שבת, ",
        }
        return switcher.get(datetime.datetime.today().isoweekday())

    # check if the time is correct
    @classmethod
    def is_time_format(cls, input_time):
        """Check if the time is correct."""
        try:
            time.strptime(input_time, '%H:%M')
            return True
        except ValueError:
            return False
