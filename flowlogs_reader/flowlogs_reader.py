#  Copyright 2015 Observable Networks
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from __future__ import print_function

from calendar import timegm
from datetime import datetime, timedelta

import boto3

ACCEPT = 'ACCEPT'
REJECT = 'REJECT'
SKIPDATA = 'SKIPDATA'
NODATA = 'NODATA'


class FlowRecord(object):
    """
    Given a VPC Flow Logs event dictionary, returns a Python object whose
    attributes match the field names in the event record. Integers are stored
    as Python int objects; timestamps are stored as Python datetime objects.
    """
    __slots__ = [
        'version',
        'account_id',
        'interface_id',
        'srcaddr',
        'dstaddr',
        'srcport',
        'dstport',
        'protocol',
        'packets',
        'bytes',
        'start',
        'end',
        'action',
        'log_status',
    ]

    def __init__(self, event):
        fields = event['message'].split()
        self.version = int(fields[0])
        self.account_id = fields[1]
        self.interface_id = fields[2]
        self.start = datetime.utcfromtimestamp(int(fields[10]))
        self.end = datetime.utcfromtimestamp(int(fields[11]))

        self.log_status = fields[13]
        if self.log_status in (NODATA, SKIPDATA):
            self.srcaddr = None
            self.dstaddr = None
            self.srcport = None
            self.dstport = None
            self.protocol = None
            self.packets = None
            self.bytes = None
            self.action = None
        else:
            self.srcaddr = fields[3]
            self.dstaddr = fields[4]
            self.srcport = int(fields[5])
            self.dstport = int(fields[6])
            self.protocol = int(fields[7])
            self.packets = int(fields[8])
            self.bytes = int(fields[9])
            self.action = fields[12]

    def __eq__(self, other):
        return all(
            getattr(self, x) == getattr(other, x) for x in self.__slots__
        )

    def __hash__(self):
        return hash(tuple(getattr(self, x) for x in self.__slots__))

    def __str__(self):
        ret = ['{}: {}'.format(x, getattr(self, x)) for x in self.__slots__]
        return ', '.join(ret)

    def to_dict(self):
        return {x: getattr(self, x) for x in self.__slots__}

    def to_message(self):
        D_transform = {
            'start': lambda dt: str(timegm(dt.utctimetuple())),
            'end': lambda dt: str(timegm(dt.utctimetuple())),
        }

        ret = []
        for attr in self.__slots__:
            transform = D_transform.get(attr, lambda x: str(x) if x else '-')
            ret.append(transform(getattr(self, attr)))

        return ' '.join(ret)

    @classmethod
    def from_message(cls, message):
        return cls({'message': message})


class FlowLogsReader(object):
    """
    Returns an object that will yield VPC Flow Log records as Python objects.
    * `log_group_name` is the name of the CloudWatch Logs group that stores
    your VPC flow logs.
    * `region_name` is the AWS region.
    * `start_time` is a Python datetime.datetime object; only the log events
    from at or after this time will be considered.
    * `end_time` is a Python datetime.datetime object; only the log events
    before this time will be considered.
    * boto_client_kwargs - other keyword arguments to pass to boto3.client
    """

    def __init__(
        self,
        log_group_name,
        region_name='us-east-1',
        start_time=None,
        end_time=None,
        boto_client_kwargs=None
    ):
        boto_client_kwargs = boto_client_kwargs or {}

        self.logs_client = boto3.client(
            'logs', region_name=region_name, **boto_client_kwargs
        )

        self.log_group_name = log_group_name

        # If no time filters are given use the last hour
        now = datetime.utcnow()
        start_time = start_time or now - timedelta(hours=1)
        end_time = end_time or now

        self.start_ms = timegm(start_time.utctimetuple()) * 1000
        self.end_ms = timegm(end_time.utctimetuple()) * 1000

    def __iter__(self):
        self.iterator = self._reader()
        return self

    def __next__(self):
        return next(self.iterator)

    def next(self):
        # For Python 2 compatibility
        return self.__next__()

    def _read_streams(self):
        kwargs = {
            'logGroupName': self.log_group_name,
            'startTime': self.start_ms,
            'endTime': self.end_ms,
            'interleaved': True,
        }

        while True:
            response = self.logs_client.filter_log_events(**kwargs)
            for event in response['events']:
                yield event

            next_token = response.get('nextToken')
            if next_token is not None:
                kwargs['nextToken'] = next_token
            else:
                break

    def _reader(self):
        # Loops through each log stream and its events, yielding a parsed
        # version of each event.
        for event in self._read_streams():
            yield FlowRecord(event)
