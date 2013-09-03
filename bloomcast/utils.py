"""Utility classes for SoG-bloomcast project.

A collection of classes that are used in other bloomcast modules.
"""

# Standard library:
from datetime import date
from datetime import datetime
from datetime import timedelta
import logging
from io import StringIO
from xml.etree import cElementTree as ElementTree
# HTTP Requests library:
import requests
# YAML library:
import yaml
# NumPy:
import numpy as np
# Matplotlib:
from matplotlib.dates import date2num
# SOG command processor:
import SOGcommand


log = logging.getLogger('bloomcast.utils')


class _Container(object):
    pass


class Config(object):
    """Placeholder for a config object that reads values from a file.
    """
    def load_config(self, config_file):
        """Load values from the specified config file into the
        attributes of the Config object.
        """
        config_dict = self._read_yaml_file(config_file)
        self._load_logging_config(config_dict)
        self.get_forcing_data = config_dict['get_forcing_data']
        self.run_SOG = config_dict['run_SOG']
        self.infiles = config_dict['infiles']
        self.results_dir = config_dict['results_dir']
        self.std_bio_ts_outfiles = {}
        self.std_phys_ts_outfiles = {}
        self.Hoffmueller_profiles_outfiles = {}
        for key in self.infiles['edits']:
            infile_dict = self._read_SOG_infile(
                self.infiles['base'], self.infiles['edits'][key])
            if key == 'avg_forcing':
                self.run_start_date = (
                    infile_dict['run_start_date']
                    .replace(hour=0, minute=0, second=0, microsecond=0))
                self.SOG_timestep = int(infile_dict['SOG_timestep'])
            self.std_bio_ts_outfiles[key] = infile_dict['std_bio_ts_outfile']
            self.std_phys_ts_outfiles[key] = infile_dict['std_phys_ts_outfile']
            self.Hoffmueller_profiles_outfiles[key] = infile_dict[
                'Hoffmueller_profiles_outfile']
        self.climate = _Container()
        self.climate.__dict__.update(config_dict['climate'])
        self._load_meteo_config(config_dict, infile_dict)
        self._load_wind_config(config_dict, infile_dict)
        self.rivers = _Container()
        self.rivers.__dict__.update(config_dict['rivers'])
        self._load_rivers_config(config_dict, infile_dict)

    def _load_logging_config(self, config_dict):
        """Load Config values for logging.
        """
        self.logging = _Container()
        self.logging.__dict__.update(config_dict['logging'])

    def _load_meteo_config(self, config_dict, infile_dict):
        """Load Config values for meteorological forcing data.
        """
        self.climate.meteo = _Container()
        self.climate.meteo.__dict__.update(
            config_dict['climate']['meteo'])
        self.climate.meteo.cloud_fraction_mapping = self._read_yaml_file(
            config_dict['climate']['meteo']['cloud_fraction_mapping'])
        forcing_data_files = infile_dict['forcing_data_files']
        self.climate.meteo.output_files = {}
        for qty in self.climate.meteo.quantities:
            self.climate.meteo.output_files[qty] = forcing_data_files[qty]

    def _load_wind_config(self, config_dict, infile_dict):
        """Load Config values for wind forcing data.
        """
        self.climate.wind = _Container()
        wind = config_dict['climate']['wind']
        self.climate.wind.station_id = wind['station_id']
        forcing_data_files = infile_dict['forcing_data_files']
        self.climate.wind.output_files = {}
        self.climate.wind.output_files['wind'] = forcing_data_files['wind']

    def _load_rivers_config(self, config_dict, infile_dict):
        """Load Config values for river flows forcing data.
        """
        self.rivers.major = _Container()
        major_river = config_dict['rivers']['major']
        self.rivers.major.station_id = major_river['station_id']
        self.rivers.minor = _Container()
        minor_river = config_dict['rivers']['minor']
        self.rivers.minor.station_id = minor_river['station_id']
        forcing_data_files = infile_dict['forcing_data_files']
        self.rivers.output_files = {}
        for river in 'major minor'.split():
            self.rivers.output_files[river] = (
                forcing_data_files[river + '_river'])

    def _read_yaml_file(self, config_file):
        """Return the dict that results from loading the contents of
        the specified config file as YAML.
        """
        with open(config_file, 'rt') as file_obj:
            return yaml.load(file_obj.read())

    def _read_SOG_infile(self, yaml_file, edit_files):
        """Return a dict of selected values read from the SOG infile.
        """
        # Mappings between SOG YAML infile keys and Config object attributes
        infile_values = {
            'initial_conditions.init_datetime': 'run_start_date',
            'numerics.dt': 'SOG_timestep',
            'timeseries_results.std_biology': 'std_bio_ts_outfile',
            'timeseries_results.std_physics': 'std_phys_ts_outfile',
            'profiles_results.hoffmueller_file': (
                'Hoffmueller_profiles_outfile'),
        }
        forcing_data_files = {
            'forcing_data.wind_forcing_file': 'wind',
            'forcing_data.air_temperature_forcing_file': 'air_temperature',
            'forcing_data.humidity_forcing_file': 'relative_humidity',
            'forcing_data.cloud_fraction_forcing_file': 'cloud_fraction',
            'forcing_data.major_river_forcing_file': 'major_river',
            'forcing_data.minor_river_forcing_file': 'minor_river',
        }
        infile_dict = {'forcing_data_files': {}}
        for infile_key in infile_values:
            value = SOGcommand.api.read_infile(
                yaml_file, edit_files, infile_key)
            result_key = infile_values[infile_key]
            infile_dict[result_key] = value
        for infile_key in forcing_data_files:
            value = SOGcommand.api.read_infile(
                yaml_file, edit_files, infile_key)
            result_key = forcing_data_files[infile_key]
            infile_dict['forcing_data_files'][result_key] = value
        return infile_dict


class ForcingDataProcessor(object):
    """Base class for forcing data processors.
    """
    def __init__(self, config):
        self.config = config
        self.data = {}

    def _valuegetter(self, data_item):
        """Return a data value.

        Override this method if data is stored in hourlies list in a
        type or data structure other than a simple value; e.g. wind
        data is stored as a tuple of components.
        """
        return data_item

    def _trim_data(self, qty):
        """Trim empty and incomplete days from the end of the data
        data list.

        Days without any data are deleted first, then days without
        data at 23:00 are deleted.
        """
        while self.data[qty]:
            if any([self._valuegetter(data[1])
                    for data in self.data[qty][-24:]]):
                break
            else:
                del self.data[qty][-24:]
        else:
            raise ValueError('Forcing data list is empty')
        while self.data[qty]:
            if self._valuegetter(self.data[qty][-1][1]) is None:
                del self.data[qty][-24:]
            else:
                break
        else:
            raise ValueError('Forcing data list is empty')

    def patch_data(self, qty):
        """Patch missing data values by interpolation.
        """
        gap_start = gap_end = None
        for i, data in enumerate(self.data[qty]):
            if self._valuegetter(data[1]) is None:
                gap_start = i if gap_start is None else gap_start
                gap_end = i
                log.debug('{0} data patched for {1[0]}'.format(qty, data))
            elif gap_start is not None:
                self.interpolate_values(qty, gap_start, gap_end)
                gap_start = gap_end = None

    def interpolate_values(self, qty, gap_start, gap_end):
        """Calculate values for missing data via linear interpolation.

        Override this method if:

        * Data is stored in data list in a type or data structure
          other than a simple value; e.g. wind data is stored as a
          tuple of components.

        * Data requires special handling for interpolation; e.g. wind
          data gaps that exceed 11 hours are to be patched but also
          reported via email.
        """
        last_value = self.data[qty][gap_start - 1][1]
        next_value = self.data[qty][gap_end + 1][1]
        delta = (next_value - last_value) / (gap_end - gap_start + 2)
        for i in range(gap_end - gap_start + 1):
            timestamp = self.data[qty][gap_start + i][0]
            value = last_value + delta * (i + 1)
            self.data[qty][gap_start + i] = (timestamp, value)


class ClimateDataProcessor(ForcingDataProcessor):
    """Climate forcing data processor base class.
    """
    def __init__(self, config, data_readers):
        self.data_readers = data_readers
        super(ClimateDataProcessor, self).__init__(config)

    def get_climate_data(self, data_type, data_month):
        """Return a list of XML objects containing the specified type of
        climate data.

        The XML objects are :class:`ElementTree` subelement instances.
        """
        params = self.config.climate.params
        params['stationID'] = getattr(
            self.config.climate, data_type).station_id
        params.update(self._date_params(data_month))
        response = requests.get(self.config.climate.url, params=params)
        tree = ElementTree.parse(StringIO(response.text))
        root = tree.getroot()
        self.raw_data.extend(root.findall('stationdata'))

    def _date_params(self, data_month=None):
        """Return a dict of the components of the specified data month
        date.

        The keys are the component names in the format required for
        requests to the :kbd:`climate.weatheroffice.gc.ca` site.

        The values are the data month date components as integers,
        with the day set to 1.

        The value of data_month defaults to yesterday's date.
        """
        if not data_month:
            data_month = date.today() - timedelta(days=1)
        params = {
            'Year': data_month.year,
            'Month': data_month.month,
            'Day': 1,
        }
        return params

    def _get_data_months(self):
        """Return a list of date objects that are the 1st day of the
        months for which we want to get data from Environment Canada.

        The list starts with January of the SOG run start date year,
        and ends with the current month, wrapping through the end of
        the run start date year if necessary.
        """
        today = date.today()
        this_year = today.year
        data_months = [date(this_year, month, 1)
                       for month in range(1, today.month + 1)]
        if self.config.run_start_date.year != this_year:
            last_year = self.config.run_start_date.year
            data_months = [date(last_year, month, 1)
                           for month in range(1, 13)] + data_months
        return data_months

    def process_data(self, qty, end_date=date.today()):
        """Process data from XML data records to a list of hourly
        timestamps and data values.
        """
        reader = self.data_readers[qty]
        self.data[qty] = []
        for record in self.raw_data:
            timestamp = self.read_timestamp(record)
            if timestamp.date() > end_date:
                break
            self.data[qty].append((timestamp, reader(record)))
        self._trim_data(qty)
        self.patch_data(qty)

    def read_timestamp(self, record):
        """Read timestamp from XML data object and return it as a
        datetime instance.
        """
        timestamp = datetime(
            int(record.get('year')),
            int(record.get('month')),
            int(record.get('day')),
            int(record.get('hour')),
        )
        return timestamp


class SOG_Relation(object):
    """A SOG_Relation object has a pair of NumPy arrays containing the
    independent and dependent data values of a data set. It also has
    attributes that contain the filespec from which the data is read,
    and the units of the data arrays.

    This is a base class for implementing specific types of relations
    such as timeseries, or profiles. This class provides
    :meth:`read_header` and :meth:`read_data` methods which may need
    to be overridden for particular types of results files
    (e.g. Hoffmueller profile file requires a custom :meth:`read_data`
    method).
    """
    def __init__(self, datafile):
        """Create a SOG_Relation instance with its datafile attribute
        initialized.
        """
        self.datafile = datafile

    def read_header(self, file_obj):
        """Read a SOG results file header, and return the
        field_names and field_units lists.
        """
        for line in file_obj:
            line = line.strip()
            if line.startswith('*FieldNames:'):
                # Drop the *FieldNames: label and keep the
                # comma-delimited list
                field_names = line.split(': ', 1)[1].split(', ')
            if line.startswith('*FieldUnits:'):
                # Drop the *FieldUnits: label and keep the
                # comma-delimited list
                field_units = line.split(': ', 1)[1].split(', ')
            if line.startswith('*EndOfHeader'):
                break
        return field_names, field_units

    def read_data(self, indep_field, dep_field):
        """Read the data for the specified independent and dependent
        fields from the data file.

        Sets the indep_data and dep_data attributes to NumPy arrays,
        and the indep_units and dep_units attributes to units strings
        for the data fields.
        """
        with open(self.datafile, 'rt') as file_obj:
            (field_names, field_units) = self.read_header(file_obj)
            indep_col = field_names.index(indep_field)
            dep_col = field_names.index(dep_field)
            self.indep_units = field_units[indep_col]
            self.dep_units = field_units[dep_col]
            self.indep_data, self.dep_data = [], []
            for line in file_obj:
                self.indep_data.append(float(line.split()[indep_col]))
                self.dep_data.append(float(line.split()[dep_col]))
        self.indep_data = np.array(self.indep_data)
        self.dep_data = np.array(self.dep_data)


class SOG_Timeseries(SOG_Relation):
    """SOG timeseries relation.
    """
    def boolean_slice(self, predicate, in_place=True):
        """Slice the independent and dependent data arrays using the
        Boolean ``predicate`` array.

        If ``in_place`` is true, replace the independent and dependent
        data arrays with the slices, otherwise, return the slices.
        """
        indep_slice = self.indep_data[predicate]
        dep_slice = self.dep_data[predicate]
        if in_place:
            self.indep_data = indep_slice
            self.dep_data = dep_slice
        else:
            return indep_slice, dep_slice

    def calc_mpl_dates(self, run_start_date):
        """Calculate matplotlib dates from the independent data array
        and the ``run_start_date``.
        """
        self.mpl_dates = np.array(date2num(
            [run_start_date + timedelta(hours=hours)
             for hours in self.indep_data]))


class SOG_HoffmuellerProfile(SOG_Relation):
    """SOG profile relation with data read from a Hoffmueller diagram
    results file.
    """
    def read_data(self, indep_field, dep_field, profile_number):
        """Read the data for the specified independent and dependent
        fields from the data file.

        Sets the indep_data and dep_data attributes to NumPy arrays,
        and the indep_units and dep_units attributes to units strings
        for the data fields.
        """
        with open(self.datafile, 'rt') as file_obj:
            (field_names, field_units) = self.read_header(file_obj)
            indep_col = field_names.index(indep_field)
            dep_col = field_names.index(dep_field)
            self.indep_units = field_units[indep_col]
            self.dep_units = field_units[dep_col]
            self.indep_data, self.dep_data = [], []
            profile_count = 1
            for line in file_obj:
                if line == '\n':
                    profile_count += 1
                    if profile_count < profile_number:
                        continue
                    if profile_count > profile_number:
                        break
                else:
                    if profile_count == profile_number:
                        self.indep_data.append(float(line.split()[indep_col]))
                        self.dep_data.append(float(line.split()[dep_col]))
        self.indep_data = np.array(self.indep_data)
        self.dep_data = np.array(self.dep_data)
