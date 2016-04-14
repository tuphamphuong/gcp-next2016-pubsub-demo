#!/usr/bin/env python
# Copyright 2014 Google Inc. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


"""Cloud Pub/Sub sample application."""

import base64
import json
import logging
import time
import urllib
import uuid

import jinja2
import webapp2
from google.appengine.api import memcache, images
from google.appengine.ext import ndb
from google.appengine.ext.ndb import blobstore
from google.appengine.ext.webapp import blobstore_handlers

import cloudstorage as gcs
import constants
import pubsub_utils
import re
from apiclient import errors

JINJA2 = jinja2.Environment(loader=jinja2.FileSystemLoader('templates'),
                            extensions=['jinja2.ext.autoescape'],
                            variable_start_string='((',
                            variable_end_string='))',
                            autoescape=True)

MAX_ITEM = 20

MESSAGE_CACHE_KEY = 'messages_key'

PROJECT_ID = 'quantum-tracker-127306'
CLOUD_STORAGE_BUCKET = 'quantum-tracker-127306'
MAX_CONTENT_LENGTH = 8 * 1024 * 1024
ALLOWED_EXTENSIONS = set(['png', 'jpg', 'jpeg', 'gif'])


class User:
    def __init__(self):
        pass


class UserPhoto(ndb.Model):
    user = ndb.StringProperty()
    blob_key = ndb.BlobKeyProperty()


class PubSubMessage(ndb.Model):
    """A model stores pubsub message and the time when it arrived."""
    message = ndb.StringProperty()
    created_at = ndb.DateTimeProperty(auto_now_add=True)


class BaseHandler(webapp2.RequestHandler):
    """ Base handler """

    def options(self):
        self.response.headers['Access-Control-Allow-Origin'] = '*'
        self.response.headers['Access-Control-Allow-Headers'] = '*'
        self.response.headers['Access-Control-Allow-Methods'] = 'POST, GET, PUT, DELETE'


class InitHandler(BaseHandler):
    """Initializes the Pub/Sub resources."""

    def __init__(self, request=None, response=None):
        """Calls the constructor of the super and does the local setup."""
        super(InitHandler, self).__init__(request, response)
        self.client = pubsub_utils.get_client()
        self._setup_topic()
        self._setup_subscription()

    def _setup_topic(self):
        """Creates a topic if it does not exist."""
        self.response.headers['Access-Control-Allow-Origin'] = '*'
        topic_name = pubsub_utils.get_full_topic_name()
        try:
            self.client.projects().topics().get(
                topic=topic_name).execute()
        except errors.HttpError as e:
            if e.resp.status == 404:
                self.client.projects().topics().create(
                    name=topic_name, body={}).execute()
            else:
                logging.exception(e)
                raise

    def _setup_subscription(self):
        """Creates a subscription if it does not exist."""
        self.response.headers['Access-Control-Allow-Origin'] = '*'
        subscription_name = pubsub_utils.get_full_subscription_name()
        try:
            self.client.projects().subscriptions().get(
                subscription=subscription_name).execute()
        except errors.HttpError as e:
            if e.resp.status == 404:
                body = {
                    'topic': pubsub_utils.get_full_topic_name(),
                    'pushConfig': {
                        'pushEndpoint': pubsub_utils.get_app_endpoint_url()
                    }
                }
                self.client.projects().subscriptions().create(
                    name=subscription_name, body=body).execute()
            else:
                logging.exception(e)
                raise

    def get(self):
        """Shows an HTML form."""
        self.response.headers['Access-Control-Allow-Origin'] = '*'
        template = JINJA2.get_template('pubsub.html')
        endpoint_url = re.sub('token=[^&]*', 'token=REDACTED',
                              pubsub_utils.get_app_endpoint_url())
        context = {
            'project': pubsub_utils.get_project_id(),
            'topic': pubsub_utils.get_app_topic_name(),
            'subscription': pubsub_utils.get_app_subscription_name(),
            'subscriptionEndpoint': endpoint_url
        }
        self.response.write(template.render(context))


class FetchMessagesHandler(BaseHandler):
    """A handler returns messages."""

    def get(self):
        """Returns recent messages as a json."""
        self.response.headers['Access-Control-Allow-Origin'] = '*'
        messages = memcache.get(MESSAGE_CACHE_KEY)
        if not messages:
            messages = PubSubMessage.query().order(
                -PubSubMessage.created_at).fetch(MAX_ITEM)
            memcache.add(MESSAGE_CACHE_KEY, messages)
        self.response.headers['Content-Type'] = ('application/json;'
                                                 ' charset=UTF-8')
        # new_messages = list()
        # for message in messages:
        #     if 'undefined' not in message:
        #         new_messages.append(messages)
        self.response.write(
            json.dumps(
                [message.message for message in messages]))


class SendMessageHandler(BaseHandler):
    """A handler publishes the given message."""

    def post(self):
        """Publishes the message via the Pub/Sub API."""
        self.response.headers['Access-Control-Allow-Origin'] = '*'
        client = pubsub_utils.get_client()
        message = self.request.get('message')
        full_message = {
            'message_data': message,
            'created': int(time.time())
        }
        user_id = self.request.get('user_id')
        if user_id and UserHandler.users.get(user_id) is not None:
            full_message['user'] = UserHandler.users.get(user_id).__dict__

        if full_message:
            topic_name = pubsub_utils.get_full_topic_name()
            body = {
                'messages': [{
                    'data': base64.b64encode(json.dumps(full_message).encode('utf-8'))
                }]
            }
            client.projects().topics().publish(
                topic=topic_name, body=body).execute()
        self.response.status = 204


class ReceiveMessageHandler(BaseHandler):
    """A handler for push subscription endpoint.."""

    def post(self):
        self.response.headers['Access-Control-Allow-Origin'] = '*'
        if constants.SUBSCRIPTION_UNIQUE_TOKEN != self.request.get('token'):
            self.response.status = 404
            return

        message = json.loads(urllib.unquote(self.request.body).rstrip('='))
        message_body = base64.b64decode(str(message['message']['data']))

        pubsub_message = PubSubMessage(message=message_body)
        pubsub_message.put()

        # Invalidate the cache
        memcache.delete(MESSAGE_CACHE_KEY)
        self.response.status = 200


class UserHandler(BaseHandler):
    users = dict()

    def get(self):
        self.response.headers['Access-Control-Allow-Origin'] = '*'
        user = UserHandler.users.get(self.request.get('user_id'))
        if user:
            result = user.__dict__
            self.response.write(json.dumps(result))
            self.response.status = 200
        else:
            self.response.write('{}')
            self.response.status = 200

    def post(self):
        """ Create user if not existing, return if existing """
        self.response.headers['Access-Control-Allow-Origin'] = '*'
        post_values = self.request.params
        user = User()
        user.user_id = str(uuid.uuid4())
        if 'name' in post_values:
            user.name = post_values['name']
        if 'avatar' in post_values:
            user.avatar = post_values['avatar']
        UserHandler.users[user.user_id] = user
        result = json.dumps(user.__dict__)
        self.response.write(result)
        self.response.status = 200


class ListUserHandler(BaseHandler):
    def get(self):
        self.response.headers['Access-Control-Allow-Origin'] = '*'
        result = []
        for key, value in UserHandler.users.iteritems():
            result.append(value.__dict__)
        self.response.write(json.dumps(result))
        self.response.status = 200


class PhotoUploadFormHandler(webapp2.RequestHandler):
    def get(self):
        upload_url = blobstore.create_upload_url('/upload_photo')
        # To upload files to the blobstore, the request method must be "POST"
        # and enctype must be set to "multipart/form-data".
        self.response.out.write("""
            <html><body>
            <form action="{0}" method="POST" enctype="multipart/form-data">
              Upload File: <input type="file" name="file"><br>
              <input type="submit" name="submit" value="Submit">
            </form>
            </body></html>""".format(upload_url))


class PhotoUploadHandler(blobstore_handlers.BlobstoreUploadHandler):
    def post(self):
        try:
            upload = self.get_uploads()[0]
            user_id = self.request.get('user_id')
            user_photo = UserPhoto(
                user=user_id,
                blob_key=upload.key())
            user_photo.put()

            self.redirect('/view_photo/%s' % upload.key())
        except:
            self.error(500)


class ViewPhotoHandler(blobstore_handlers.BlobstoreDownloadHandler):
    def get(self, photo_key):
        if not blobstore.get(photo_key):
            self.error(404)
        else:
            self.send_blob(photo_key)


def create_cs_file(name, content):
    """Create a file.
    The retry_params specified in the open call will override the default
    retry params for this particular file handle.
    """
    write_retry_params = gcs.RetryParams(backoff_factor=1.1)
    gcs_file = gcs.open(name,
                        'w',
                        content_type='text/plain',
                        retry_params=write_retry_params)
    gcs_file.write(content)
    gcs_file.close()


def get_cs_file(filename):
    gcs_file = gcs.open(filename)
    response = gcs_file.readline()
    gcs_file.close()
    return response


def get_size(fileobject):
    fileobject.seek(0, 2)  # move the cursor to the end of the file
    size = fileobject.tell()
    return size


APPLICATION = webapp2.WSGIApplication(
    [
        (r'/', InitHandler),
        (r'/users', UserHandler),
        (r'/users/', ListUserHandler),
        (r'/fetch_messages', FetchMessagesHandler),
        (r'/send_message', SendMessageHandler),
        (r'/receive_message', ReceiveMessageHandler),
        ('/photo', PhotoUploadFormHandler),
        ('/upload_photo', PhotoUploadHandler),
        ('/view_photo/([^/]+)?', ViewPhotoHandler),
    ], debug=True)
