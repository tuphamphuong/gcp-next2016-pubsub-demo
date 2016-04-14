
'use strict';

var pubsub = pubsub || angular.module('pubsub', []);

/**
 * PubsubController.
 *
 * @NgInject
 */
pubsub.PubsubController = function($http, $log, $timeout) {
  this.promise = null;
  this.logger = $log;
  this.http = $http;
  this.timeout = $timeout;
  this.interval = 1;
  this.isAutoUpdating = true;
  this.failCount = 0;
  this.show_messages = true;
  this.show_all_users = false;
  this.count_users = 0;
  this.all_users = [];
  this.username = '';
  this.define_add = true;
  this.userObj = null;
  this.fetchMessages();
  this.fetchAllUsers();
  this.getUserInfo();
};

pubsub.PubsubController.MAX_FAILURE_COUNT = 10000;

pubsub.PubsubController.TIMEOUT_MULTIPLIER = 1000;

pubsub.PubsubController.prototype.getUserInfo = function() {

  var self = this;
  var userObj = localStorage.getItem('userObj');
  console.log(userObj);
  if(userObj !== null && (typeof userObj === 'string' || userObj instanceof String) )
  {
    var userObjParse = JSON.parse( userObj );
    var user_id = userObjParse.user_id;
    self.http({
      method: 'GET',
      url: '/users?user_id='+user_id,
      headers: {'Content-Type': 'application/x-www-form-urlencoded'}
    }).success(function(data, status) {
      
      console.log(data);
      if( typeof data == 'object' && data.hasOwnProperty("user_id") )
      {
        self.userObj = data;
        self.username = data.name;
        localStorage.setItem("userObj", JSON.stringify(data));
        angular.element(".username").addClass("username_active");
        self.define_add = false;
      }
      else{
        self.userObj = null;
        self.username = '';
        localStorage.clear();
        self.define_add = true;
      }
    }).error(function(data, status) {

      self.logger.error('Failed to send the message. Status: ' + status + '.');
    });
  }
};

pubsub.PubsubController.prototype.userCreate = function(username) {

  var self = this;
  var data_param = $.param({
      name: username,
  });

  if(username !== undefined && username != "")
  {
    if(username.length >= 5)
    {
      self.http({
        method: 'POST',
        url: '/users',
        data: data_param,
        headers: {'Content-Type': 'application/x-www-form-urlencoded'}
      }).success(function(data, status) {

        localStorage.setItem("userObj", JSON.stringify(data));
        self.all_users.push(data);
        angular.element(".username").addClass("username_active");
        self.define_add = false;
        
      }).error(function(data, status) {

        self.logger.error('Failed to send the message. Status: ' + status + '.');
      });
    }else{
      alert("username string length greater than 5 characters");
    }
  }
  else{
    alert("username is undefined");
  }
};

/**
 * Toggles the auto update flag.
 */
pubsub.PubsubController.prototype.toggleAutoUpdate = function() {
  this.isAutoUpdating = !this.isAutoUpdating;
  if (this.isAutoUpdating) {
    this.logger.info('Start fetching.');
    this.fetchMessages();
  } else if (this.promise !== null) {
    this.logger.info('Cancel the promise.');
    this.timeout.cancel(this.promise);
    this.promise = null;
  }
};

/**
 * Sends a message
 *
 * @param {string} message
 */
pubsub.PubsubController.prototype.sendMessage = function(message) {

  var self = this;
  var data_obj = {};
  data_obj.message = message;

  if(localStorage.getItem('userObj') !== null)
  {
    var userObj = JSON.parse(localStorage.getItem('userObj'));
    data_obj.user_id = userObj.user_id;
  }

  var data_param = $.param(data_obj);

  self.http({
    method: 'POST',
    url: '/send_message',
    data: data_param,
    headers: {'Content-Type': 'application/x-www-form-urlencoded'}
  }).success(function(data, status) {
    self.message = null;
  }).error(function(data, status) {
    self.logger.error('Failed to send the message. Status: ' + status + '.');
  });
};

/**
 * Continuously fetches messages from the server.
 */
pubsub.PubsubController.prototype.fetchMessages = function() {
  var self = this;
  self.http.get('/fetch_messages')
    .success(function(data, status) {

      var getData = [];

      for (var i = 0; i < data.length; i++)
      {
        if ( self.isJsonString(data[i]) === true )
        {
          var dataParse = JSON.parse(data[i]);

          dataParse.created = new Date(dataParse.created*1000);

          if(dataParse.hasOwnProperty("user") === false)
          {
            dataParse.username = "Anoymous";
          }
          else{
            dataParse.username = dataParse.user.name;
          };
          getData.push(dataParse);
        };
      };

      self.messages = getData;

      self.failCount = 0;
  })
  .error(function(data, status) {
    self.logger.error('Failed to receive the messages. Status: ' +
                      status + '.');
    self.failCount += 1;
  });

  if (self.failCount < pubsub.PubsubController.MAX_FAILURE_COUNT)
  {
    if (self.isAutoUpdating)
    {
      self.promise = self.timeout(
        function() {
          self.fetchMessages();
          self.fetchAllUsers();
        },
        self.interval * pubsub.PubsubController.TIMEOUT_MULTIPLIER);
    }
  }
  else {
    self.errorNotice = 'Maximum failure count reached, ' +
      'so stopped fetching messages.';
    self.logger.error(self.errorNotice);
    self.isAutoUpdating = false;
    self.failCount = 0;
  }
};

pubsub.PubsubController.prototype.onClickTabs = function (tab) {

  var self = this;
  angular.element(".active").removeClass("active");

  if(tab == "allUsers")
  {
    angular.element(".allUsers").addClass("active");
    self.show_messages = false;
    self.show_all_users = true;
  }
  else{
    angular.element(".messages").addClass("active");
    self.show_messages = true;
    self.show_all_users = false;
  }
};

/**
 * Check is json or string
 */
pubsub.PubsubController.prototype.isJsonString = function (str) {

  try {
      JSON.parse(str);
  } catch (e) {

    if (str instanceof Object == false)
    {
      return false;
    }
    else {
      return true;
    }
  }
  return true;
};

/**
 * Continuously fetches all users from the server.
 */
pubsub.PubsubController.prototype.fetchAllUsers = function () {

  var self = this;

  self.http.get('/users/')
    .success(function(data, status) {

      var getData = [];

      for (var i = 0; i < data.length; i++)
      {
        if ( self.isJsonString(data[i]) === true )
        {
          getData.push(data[i]);
        };
      };

      self.all_users = getData;
      self.count_users = getData.length;
      self.failCount = 0;
  })
  .error(function(data, status) {
    self.logger.error('Failed to receive the messages. Status: ' +
                      status + '.');
    self.failCount += 1;
  });
};
