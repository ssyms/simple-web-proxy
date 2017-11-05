var blockedurls = []

$(document).ready(function(){
    //connect to the socket server.
    var socket = io.connect('http://' + document.domain + ':' + location.port + '/test');
    var requests_received = [];

    //receive details from server
    socket.on('update_console', function(msg) {
        //maintain a list of ten numbers
        if (requests_received.length >= 40){
            requests_received.shift()
        }
        requests_received.push(msg.req);
        requests_string = $('#log').html();
        if(msg.blocked == 1) {
          requests_string = '<li class="list-group-item list-group-item-danger">' + msg.req.toString() + '</li>' + requests_string;
        } else {
          requests_string = '<li class="list-group-item list-group-item-success">' + msg.req.toString() + '</li>' + requests_string;
        }

        $('#log').html(requests_string);
    });

});

function blockurl() {
  var socket = io.connect('http://' + document.domain + ':' + location.port + '/url');
  var blockurl = document.getElementById("blockurl").value;
  blockedurls.push(blockurl)
  urls_string = '';
  for (var i = 0; i < blockedurls.length; i++){
      urls_string = urls_string + '<p>' + blockedurls[i].toString() + '</p>';
  }
  $('#blocked').html(urls_string);
  socket.emit('block url', {data: blockurl});

}
