app.factory("notificationService", function($http) {
  return {
     getNotification: function(groupID, notType, params={}) {
		var url = "/admin/get/notification/" + groupID + "/" + notType
        return $http.get(url, {params: params});

     }

  };
});