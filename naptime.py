"""naptime provides a nice Pythonic interface to web services. Services are
defined using a declarative syntax.
    
    >>> class Upcoming(Service):
    ...     url = "http://upcoming.yahooapis.com/services/rest/?api_key=%(api_key)s&format=%(format)s&method=%(method)s"
    ...     api_key = "b852383820"
    ...     methods = {
    ...         "event.getInfo": ["event_id"]
    ...     }
    ...
    >>> u = Upcoming()
    >>> u.event.getInfo(event_id=22) # args can be passed positionally or as keywords
    {u'rsp': {u'stat': u'ok', u'version': 1, u'event': [{u'venue_state_id': 5, u'utc_start': u'2003-11-14 08:00:00 UTC', u'venue_city': u'Hollywood', u'date_posted': u'2003-09-13', u'venue_id': 90784, u'user_id': 3, u'venue_name': u'The Music Box @ Fonda', u'personal': 0, u'venue_address': u'6126 Hollywood Blvd.', u'venue_state_code': u'ca', u'id': 22, u'latitude': 0, u'venue_country_name': u'United States', u'venue_country_code': u'us', u'start_date': u'2003-11-14', u'ticket_price': u'', u'description': u'w/ Nada Surf', u'end_date': u'', u'tags': u'', u'start_time': u'', u'ticket_url': u'', u'metro_id': 1, u'venue_url': u'http://www.henryfondatheater.com', u'venue_zip': 90028, u'geocoding_precision': u'address', u'venue_country_id': 1, u'venue_state_name': u'California', u'ticket_free': u'', u'photo_url': u'', u'category_id': 1, u'name': u'Death Cab For Cutie', u'url': u'', u'longitude': 0, u'utc_end': u'2003-11-14 11:00:00 UTC', u'venue_phone': u'323-464-0808', u'selfpromotion': 0, u'end_time': u'', u'geocoding_ambiguous': 0}]}}

Features:

  * Supports JSON and XML.

  * API keys can be specified in the service definition and are automatically
    sent with all requests.

  * Cookies are kept for the lifetime of a Service instance.

  * Last-Modified and ETag headers are used to cache results, however expires
    headers and redirect response are ignored.

  * Instances of Service can be safely pickled. After unpickling, the session
    can be continued where it was left off. Cookies are remembered, but the
    cache is flushed.

See the docstring of the Service class for more information.

naptime provides a clean interface for making requests, but currently returns
results as generic Python data structures. An obvious improvement would be to
allow expected responses to be defined and return rich model objects in a
similar manner to ActiveRecord.

Post values are always sent application/x-www-form-urlencoded.

"""
from cookielib import CookieJar
from datetime import date, datetime
from decimal import Decimal
from json import load
from logging import getLogger
from re import compile as re_compile
from urllib import urlencode
from urllib2 import build_opener, HTTPCookieProcessor, \
        HTTPDefaultErrorHandler, HTTPError, HTTPHandler, HTTPSHandler, \
        Request, URLError
from urlparse import urlparse
from xml.etree.cElementTree import ElementTree


USER_AGENT = "naptime/0.1"
DEFAULT_FORMAT = "json"
ISO_TIME_FORMAT = "%Y-%m-%dT%H:%M:%S"


# a hostname is a set of parts joined by dots, parts consist of numbers or
# letters, e.g. localhost, google.com, 127.0.0.1
HOSTNAME_RE = re_compile(r"^[a-zA-Z0-9]+(-[a-zA-Z0-9]+)*(\.[a-zA-Z0-9]+(-[a-zA-Z0-9]+)*)*$")


log = getLogger()


def iso_date_str(s):
    no_tz = s.split(u"+")[0]
    no_usec = no_tz.split(u".")[0]
    return datetime.strptime(no_usec, ISO_TIME_FORMAT).date()


def bool_str(s):
    return s == "true"


def serialize_value(v):
    """Serialize Python types to strings that the Wonga API can understand.
    
      * Replace None values with empty string.

      * Booleans become "true" or "false".

      * Dates are ISO formatted.
    """
    if v is None:
        return u""
    elif isinstance(v, bool):
        return "true" if v else "false"
    elif isinstance(v, (date, datetime)):
        return v.strftime(ISO_TIME_FORMAT)
    elif isinstance(v, Decimal):
        return u"%0.02f" % v
    else:
        return unicode(v)


def serialize_values(d):
    return dict(((k, serialize_value(v)) for k, v in d.iteritems()))


def unserialize_values(values, typemap):
    unserialized = {}
    for k, v in values.iteritems():
        unserialize = typemap.get(k, str)
        unserialized[k] = unserialize(v)
    return unserialized


def valid_hostname(hostname):
    return HOSTNAME_RE.match(hostname) is not None


def encode_post(data):
    """Encode data for POST requests. If data is a dictionary, it will be
    url-encoded, otherwise it is just coerced to unicode. If you're passing
    XML or JSON, encode the data before passing it to a Method.
   
    """
    if isinstance(data, dict):
        return urlencode(data)
    else:
        return unicode(data)


class ServiceException(Exception):
    pass


class DefaultErrorHandler(HTTPDefaultErrorHandler):
    """Handle HTTP errors gracefully. From Dive Into Python -
    http://www.diveintopython.org/http_web_services/etags.html.
    
    """
    def http_error_default(self, req, fp, code, msg, headers):
        result = HTTPError(req.get_full_url(), code, msg, headers, fp)
        result.status = code
        return result


class Service(object):
    """Represent a RESTful service. Allows methods and parameters of the remote
    service to be defined in a declarative way. Decodes XML or JSON or returns
    response as raw data.

    Url construction can be customised by adding parameters to the url
    attribute. E.g.:

        http://upcoming.yahooapis.com/services/rest/?api_key=%(api_key)s&format=%(format)s&method=%(method)s

    Available parameters are:

        api_key
        format ("json", "xml" or "raw", defaults to "json")
        method

    All other parameters are currently added to the query string. Subclass and
    override _build_url for even more control over url construction.

    """
    def __init__(self):
        """Initialise by checking class attributes are valid. url and
        methods are required. format, api_key and name are optional and have
        sensible defaults.
        
        """
        if getattr(self, "cookies", None) is None:
            self.cookies = CookieJar()

        # check class attributes
        self._validate_attributes()

        # set up url opener and cookie handling
        self.opener = self._build_opener()

        # set up a request cache for handling 304 Not Modified
        # cache format is {url: {"last_modified": "Thu, 15 Apr 2004 19:45:21 GMT", "etag": "a1b2c3", "document": "..."}}
        # NB: because history is here, it is per-session
        self._history = {}

        # add methods
        self._build_methods()

    def _validate_attributes(self):
        """Check that required attributes (url, methods and format) have been
        set and have valid values.
        
        """
        # url
        url_parsed = urlparse(self.url)
        if url_parsed.scheme not in ("http", "https"):
            raise ValueError("Unknown url scheme '%s', please use http or https"
                    % url_parsed.scheme)
        elif not valid_hostname(url_parsed.hostname):
            raise ValueError("Bad host name '%s', please use a valid"
                    u" host name or IP address" % url_parsed.hostname)

        # methods
        if self.methods is None or not hasattr(self.methods, "get"):
            raise ValueError("Methods dictionary not found in class attributes")

        # format (optional)
        if getattr(self, "format", "").lower() not in ("", "json", "xml", "raw"):
            raise ValueError("Unknown format '%s', please use json, xml or raw" %
                    getattr(self, "format", ""))

        # response_handlers (optional)
        rh = getattr(self, "response_handlers", [])
        if not hasattr(rh, "__iter__"):
            raise ValueError("response_handlers must be a sequence of callables")

    def _build_opener(self):
        """Build an url opener that remembers cookies for the life of the
        Service object. Override this method if you need to open urls behind
        HTTP basic auth or do other fancy urllib2 tricks.
        
        """
        # add handlers to opener to preserve cookies and handle errors
        handlers = [
            HTTPCookieProcessor(self.cookies),
            DefaultErrorHandler(),
        ]

        # add HTTP and HTTPS handlers with debugging enabled
        if getattr(self, "debug", False):
            handlers += [HTTPHandler(debuglevel=1), HTTPSHandler(debuglevel=1)]

        opener = build_opener(*handlers)
        opener.addheaders = [
            ("User-Agent", USER_AGENT),
        ]
        return opener

    def _content_type(self):
        format_lower = getattr(self, "format", DEFAULT_FORMAT).lower()
        if format_lower == "json":
            return "application/json"
        elif format_lower == "xml":
            return "text/xml"
        else:
            return "application/x-www-form-urlencoded"

    def _build_methods(self):
        """Create Methods and MethodSets from the API spec."""
        for name, param_names in self.methods.iteritems():
            if "." in name:
                first_name = name.split(".")[0]
                setattr(self, first_name, MethodSet(self, first_name))
            else:
                setattr(self, name, Method(self, name, param_names))

    def __getstate__(self):
        """Allow Service instances to be pickled. The state of a instance is just
        the set of cookies provided by the service. Return these to pickle.
        
        """
        return list(self.cookies)

    def __setstate__(self, state):
        """Recreate an instance by unpacking a list of cookies into a new
        CookieJar object. Call __init__ to create Methods and MethodSets.
        
        """
        self.cookies = CookieJar()
        for c in state:
            self.cookies.set_cookie(c)
        self.__init__()

    def __repr__(self):
        return "<Service: %s>" % self.__class__.__name__

    def request(self, method, raw_data=None, **kwargs):
        """Make an HTTP request to the RESTful service. For GET requests, cached
        responses are used to send If-Modified-Since and If-None-Match headers
        to the server.  If the server returns 304 Not Modified, the locally
        cached (already decoded) version is returned.
        
        """
        # get HTTP verb for request
        is_get = method not in getattr(self, "post_methods", [])

        # build url and Request object
        url = self._build_url(is_get, method, kwargs)
        request = self.build_request(url, is_get, kwargs, raw_data)

        # send the request
        try:
            response = self.opener.open(request)
        except (HTTPError, URLError), e:
            log.error(e)
            raise ServiceException(u"Error sending request: %s" % e)

        # check status code
        status = getattr(response, "status", 200)
        if status not in (200, 304):
            raise ServiceException(u"Error sending request: %s" % response)

        # return a decoded version of the request, caching GET requests if
        # possible
        if not is_get:
            out = self._decode(response)
        else:
            if url not in self._history or status != 304:
                # update cache
                self._history[url] = {
                    "document":         self._decode(response),
                    "etag":             response.headers.get("ETag", ""),
                    "last_modified":    response.headers.get("Last-Modified", "")
                }

            # returned cached document value
            out = self._history[url]["document"]

        # run the response through each of the response handlers
        response_handlers = getattr(self, "response_handlers", [])
        return reduce(lambda x, y: y(x), response_handlers, out) 

    def _build_url(self, is_get, method, params):
        """Build the url for a resource. Different services map a method name,
        argument list and format to urls in quite different ways, e.g.:
            
            {"method": "statuses/show", "format": "json", "params": {"id": 123}}
            http://twitter.com/statuses/show/123.json

            {"method": "event.getInfo", "format": "json", "params": {"event_id": 123}}
            http://upcoming.yahooapis.com/services/rest/?api_key=123&format=json&method=event.getInfo&event_id=123

        The base API url is constructed by interpolating method, format and
        api_key into the url provided to the constructor. Additional parameters
        are then appended to the query string.

        This approach is not flexible enough for Twitter's API however. Subclass
        Service and override _build_call for more flexibility.

        """
        concrete_url = self.url % {
            "api_key":  getattr(self, "api_key", ""),
            "format":   getattr(self, "format", DEFAULT_FORMAT),
            "method":   method
        }
        if is_get:
            qs = urlencode(params)
            join_char = "&" if "?" in concrete_url else "?"
            return join_char.join((concrete_url, qs))
        else:
            return concrete_url

    def build_request(self, url, is_get=True, kwargs=None, raw_data=None):
        """Build an urllib2 Request object for the call. Add If-Modified-Since
        and If-None-Match headers if we have a cached version of the page.

        """
        headers = {}
        enc_data = None
        if not is_get:
            if raw_data is None and kwargs is None:
                raise ValueError(u"Provide either raw_data or kwargs")
            post_data = raw_data if raw_data is not None else kwargs
            enc_data = encode_post(post_data)
            headers = {
                "Content-Type":     self._content_type(),
                "Content-Length":   len(enc_data)
            }

        # add If-Modified-Since and If-None-Match headers if we've seen this
        # request before
        if is_get and url in self._history:
            hist = self._history[url]
            if hist["last_modified"]:
                headers["If-Modified-Since"] = hist["last_modified"]
            if hist["etag"]:
                headers["If-None-Match"] = hist["etag"]

        return Request(url, enc_data, headers)

    def _decode(self, response):
        """Decode the service response, which is a file-like object containing
        XML, JSON or raw data, and return an ElementTree or a simple Python data
        structure, respectively.
        
        """
        # get the right parser and exception type for the response format
        format_lower = getattr(self, "format", DEFAULT_FORMAT).lower()
        if format_lower == "json":
            parse = load
            exception_type = ValueError
        elif format_lower == "xml":
            parse = lambda fp: ElementTree(file=fp)
            exception_type = SyntaxError
        elif format_lower == "raw":
            parse = lambda r: r.read()
            exception_type = ValueError
        else:
            raise ValueError("Unknown format '%s', please use json, xml or raw" %
                    self.format)

        # run the parser return the results unmodified
        try:
            return parse(response)
        except exception_type, e:
            log.error(e)
            if response.read() == "":
                return None
            else:
                raise ServiceException("Error parsing service response: %s." % e)


class Method(object):
    """Represent a single method provided by a RESTful service and provide
    parameter validation. Method objects are created by Service and use
    Service.request to perform requests.
    
    """
    def __init__(self, service, name, param_names):
        self.service = service
        self.name = name
        self.param_names = param_names
        self.__doc__ = self._generate_docstring()

    def _generate_docstring(self):
        """Create some generic but hopefully useful documentation for this
        method.
        
        """
        doc = "Call %s method of service %s. " % \
                (self.name, self.service.__class__.__name__)
        if len(self.param_names) == 1:
            doc += "Argument: %s" % self.param_names[0]
        elif len(self.param_names) > 1:
            doc += "Arguments: %s" % ", ".join(self.param_names)
        else:
            doc += "No arguments."
        return doc

    def __repr__(self):
        return "<Method: %s>" % self.name

    def __call__(self, *args, **kwargs):
        """Sent a request to the Service."""
        raw_data = kwargs.get("raw_data", None)
        if raw_data is not None:
            return self.service.request(self.name, raw_data=raw_data)
        else:
            arg_dict = dict(zip(self.param_names, args))
            arg_dict.update(kwargs)
            unknown_param_names = set(kwargs.keys()).difference(set(self.param_names))
            if unknown_param_names:
                raise TypeError("%s() got unexpected keyword arguments '%s'" %
                        (self.name, u"', '".join(unknown_param_names)))

            return self.service.request(self.name, **arg_dict)


class MethodSet(object):
    """Represent a set of methods in a dot-separated namespace.
    
    Many RESTful services, e.g. Flickr, Upcoming, use dot-separated names for
    methods, such as event.getInfo or flickr.people.getInfo. MethodSet allows
    dotted names to be expressed in Python and the correct method name
    constructed.

    >>> class Upcoming(Service):
    ...     url = "http://upcoming.yahooapis.com/services/rest/?api_key=%(api_key)s&format=%(format)s&method=%(method)s"
    ...     api_key = "b852383820"
    ...     methods = {
    ...         "event.getInfo": ["event_id"]
    ...     }
    ...
    >>> u = Upcoming()
    >>> u.event
    <MethodSet: event>
    >>> u.event.getInfo
    <Method: event.getInfo>
    
    """
    def __init__(self, service, name):
        self.service = service
        self.name = name

        self._build_methods()

    def __repr__(self):
        return "<MethodSet: %s>" % self.name

    def _build_methods(self):
        """Create Methods and MethodSets from the API spec."""
        for name, param_names in self.service.methods.iteritems():
            if name.startswith(self.name):
                suffix_name = ".".join(name.split(".")[1:])
                if "." in suffix_name:
                    first_name = suffix_name.split(".")[0]
                    setattr(self, suffix_name, MethodSet(self.service, first_name))
                else:
                    setattr(self, suffix_name, Method(self.service, name, param_names))


if __name__ == "__main__":
    from doctest import testmod
    testmod()
