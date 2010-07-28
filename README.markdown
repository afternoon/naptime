Naptime
=======

Naptime provides a nice Pythonic interface to web services. Services are defined
using a declarative syntax.
    
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

Features
--------

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
