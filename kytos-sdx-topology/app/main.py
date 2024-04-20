"""
Main module of amlight/sdx Kytos Network Application.
"""
import os
import requests
from napps.kytos.sdx_topology.convert_topology import ParseConvertTopology \
          # pylint: disable=E0401
from napps.kytos.sdx_topology import settings, utils, topology_mock \
        # pylint: disable=E0401

from kytos.core import KytosNApp, log, rest
from kytos.core.events import KytosEvent
from kytos.core.helpers import listen_to
from kytos.core.rest_api import (HTTPException, JSONResponse, Request,
                                 content_type_json_or_415, get_json_or_400)

HSH = "##########"
URN = "urn:sdx:"


class Main(KytosNApp):  # pylint: disable=R0904
    """Main class of amlight/sdx NApp.

    This class is the entry point for this NApp.
    """

    def setup(self):
        """Replace the '__init__' method for the KytosNApp subclass.

        The setup method is automatically called by the controller when your
        application is loaded.

        So, if you have any setup routine, insert it here.
        """
        self.event_info = {}  # pylint: disable=W0201
        self.sdx_topology = {}  # pylint: disable=W0201
        self.version_control = 0  # pylint: disable=W0201
        OXPO_ID = int(os.environ.get("OXPO_ID"))
        oxpo_names_str = os.environ.get("OXPO_NAMES")
        self.oxpo_name = oxpo_names_str.split(",")[OXPO_ID]
        oxpo_urls_str = os.environ.get("OXPO_URLS")
        self.oxpo_urls_list = oxpo_urls_str.split(",")
        self.oxpo_url = oxpo_urls_str.split(",")[OXPO_ID]
        # mapping from IDs used by kytos and SDX
        # ex: urn:sdx:port:sax.net:Sax01:40 <--> cc:00:00:00:00:00:00:01:40
        self.kytos2sdx = {}
        self.sdx2kytos = {}

    def execute(self):
        """Run after the setup method execution.

        You can also use this method in loop mode if you add to the above setup
        method a line like the following example:

            self.execute_as_loop(30)  # 30-second interval.
        """
        self.version_control = 1

    def shutdown(self):
        """Run when your NApp is unloaded.

        If you have some cleanup procedure, insert it here.
        """

    @listen_to("kytos/topology.unloaded")
    def unload_topology(self):  # pylint: disable=W0613
        """Function meant for validation, to make sure that the version control
        has been loaded before all the other functions that use it begins to
        call it."""
        self.version_control = 0  # pylint: disable=W0201

    @staticmethod
    def get_kytos_topology():
        """retrieve topology from API"""
        kytos_topology_url = os.environ.get("KYTOS_TOPOLOGY")
        kytos_topology = requests.get(
                kytos_topology_url, timeout=10).json()
        result = kytos_topology["topology"]
        return result

    def validate_sdx_topology(self):
        """ return 200 if validated topology following the SDX data model"""
        try:
            sdx_topology_validator = os.environ.get("SDXTOPOLOGY_VALIDATOR")
            response = requests.post(
                    sdx_topology_validator,
                    json=self.sdx_topology,
                    timeout=10)
        except ValueError as exception:
            log.info("validate topology result %s %s", exception, 401)
            raise HTTPException(
                    401,
                    detail=f"Path is not valid: {exception}"
                ) from exception
        result = response.json()
        return {"result": response.json(), "status_code": response.status_code}

    def convert_topology(self, event_type=None, event_timestamp=None):
        """Function that will take care of update the self version control containing
        the version control that will be updated every time a change is
        detected in kytos topology, and return a new sdx topology"""
        try:
            if self.version_control > 0 and event_type is not None:
                if event_type == "administrative":
                    timestamp = utils.get_timestamp()
                    self.version_control += 1
                elif event_type == "operational":
                    timestamp = event_timestamp
                else:
                    return {"result": topology_mock.topology_mock(),
                            "status_code": 401}
                topology_converted = ParseConvertTopology(
                    topology=self.get_kytos_topology(),
                    version=self.version_control,
                    timestamp=timestamp,
                    model_version='2.0.0',
                    oxp_name=self.oxpo_name,
                    oxp_url=self.oxpo_url,
                    oxp_urls_list = self.oxpo_urls_list,
                ).parse_convert_topology()
                return {"result": topology_converted, "status_code": 200}
            return {"result": topology_mock.topology_mock(),
                    "status_code": 401}
        except Exception as err:  # pylint: disable=W0703
            log.info("validation Error, status code 401:", err)
            return {"result": "Validation Error", "status_code": 401}

    def post_sdx_topology(self, event_type=None, event_timestamp=None):
        """ return the topology following the SDX data model"""
        # pylint: disable=W0201
        try:
            if event_type is not None:
                converted_topology = self.convert_topology(
                        event_type, event_timestamp)
                log.info("############# Converted topology ##############:")
                log.info(converted_topology["status_code"])
                log.info("############# Converted topology ##############:")
                if converted_topology["status_code"] == 200:
                    topology_updated = converted_topology["result"]
                    self.sdx_topology = {
                        "id": topology_updated["id"],
                        "name": topology_updated["name"],
                        "version": topology_updated["version"],
                        "model_version": topology_updated["model_version"],
                        "timestamp": topology_updated["timestamp"],
                        "nodes": topology_updated["nodes"],
                        "links": topology_updated["links"],
                        "services": topology_updated["services"],
                        }
            else:
                log.info("############# Mock topology ##############:")
                log.info(event_type)
                log.info("############# Converted topology ##############:")
                self.sdx_topology = topology_mock.topology_mock()
            evaluate_topology = self.validate_sdx_topology()
            if evaluate_topology["status_code"] == 200:
                self.kytos2sdx = topology_updated.get("kytos2sdx", {})
                self.sdx2kytos = topology_updated.get("sdx2kytos", {})

                return {"result": self.sdx_topology,
                        "status_code": evaluate_topology["status_code"]}
            return {"result": evaluate_topology['result'],
                    "status_code": evaluate_topology['status_code']}
        except Exception as err:  # pylint: disable=W0703
            log.info("No SDX Topology loaded, status_code 401:", err)
        return {"result": "No SDX Topology loaded", "status_code": 401}

    @listen_to(
            "kytos/topology.link_*",
            "kytos/topology.switch.*",
            pool="dynamic_single")
    def listen_event(self, event=None):
        """Function meant for listen topology"""
        if event is not None:
            dpid = ""
            if event.name in settings.ADMIN_EVENTS:
                switch_event = {
                        "version/control.initialize": True,
                        "kytos/topology.switch.enabled": True,
                        "kytos/topology.switch.disabled": True
                        }
                if switch_event.get(event.name, False):
                    event_type = "administrative"
                    dpid = event.content["dpid"]
                else:
                    event_type = None
            elif event.name in settings.OPERATIONAL_EVENTS and \
                    event.timestamp is not None:
                event_type = "operational"
            else:
                event_type = None
            if event_type is None:
                return {"event": "not action event"}
            response = self.post_sdx_topology(event_type, event.timestamp)
            return response
        return {"event": "not action event"}

    @rest("v1/version/control", methods=["GET"])
    def get_version_control(self, _request: Request) -> JSONResponse:
        """return true if kytos topology is ready"""
        name = "version/control.get"
        content = {"dpid": ""}
        event = KytosEvent(name=name, content=content)
        event_type = "administrative"
        log.info("############# get version control ##############:")
        response = self.post_sdx_topology(event_type, event.timestamp)
        log.info("############# response version control ##############:")
        result = {}
        if response["status_code"]:
            if response["status_code"] == 200:
                if response["result"]:
                    result = response["result"]
        return JSONResponse(result)

    # rest api tests
    @rest("v1/validate_sdx_topology", methods=["POST"])
    def get_validate_sdx_topology(self, request: Request) -> JSONResponse:
        """ REST to return the validated sdx topology status"""
        # pylint: disable=W0201
        content = get_json_or_400(request, self.controller.loop)
        self.sdx_topology = content.get("sdx_topology")
        if self.sdx_topology is None:
            self.sdx_topology = topology_mock.topology_mock()
        response = self.validate_sdx_topology()
        result = response["result"]
        status_code = response["status_code"]
        return JSONResponse(result, status_code)

    @rest("v1/convert_topology/{event_type}/{event_timestamp}")
    def get_converted_topology(self, request: Request) -> JSONResponse:
        """ REST to return the converted sdx topology"""
        event_type = request.path_params["event_type"]
        event_timestamp = request.path_params["event_timestamp"]
        response = self.convert_topology(event_type, event_timestamp)
        result = response["result"]
        status_code = response["status_code"]
        return JSONResponse(result, status_code)

    @rest("v1/post_sdx_topology/{event_type}/{event_timestamp}")
    def get_sdx_topology(self, request: Request) -> JSONResponse:
        """ REST to return the sdx topology loaded"""
        event_type = request.path_params["event_type"]
        event_timestamp = request.path_params["event_timestamp"]
        response = self.post_sdx_topology(event_type, event_timestamp)
        result = response["result"]
        status_code = response["status_code"]
        return JSONResponse(result, status_code)

    @rest("v1/listen_event", methods=["POST"])
    def get_listen_event(self, request: Request) -> JSONResponse:
        """consume call listen Event"""
        try:
            result = get_json_or_400(request, self.controller.loop)
            name = result.get("name")
            content = result.get("content")
            event = KytosEvent(
                    name=name, content=content)
            # self.controller.buffers.app.put(event)
            event_result = self.listen_event(event)
            return JSONResponse(event_result)
        except requests.exceptions.HTTPError as http_error:
            raise SystemExit(
                    http_error, detail="listen topology fails") from http_error

    @rest("v1/l2vpn_ptp", methods=["POST"])
    def create_l2vpn_ptp(self, request: Request) -> JSONResponse:
        """ REST to create L2VPN ptp connection."""
        content = get_json_or_400(request, self.controller.loop)

        evc_dict = {
            "name": None,
            "uni_a": {},
            "uni_z": {},
            "dynamic_backup_path": True,
        }

        for attr in evc_dict:
            if attr not in content:
                msg = f"missing attribute {attr}"
                log.warn(f"EVC creation failed: {msg}. request={content}")
                return JSONResponse({"result": msg}, 400)
            if "uni_" in attr:
                sdx_id = content[attr].get("port_id")
                kytos_id = self.sdx2kytos.get(sdx_id)
                if not sdx_id or not kytos_id:
                    msg = f"unknown value for {attr}.port_id ({sdx_id})"
                    log.warn(f"EVC creation failed: {msg}. request={content}")
                    return JSONResponse({"result": msg}, 400)
                evc_dict[attr]["interface_id"] = kytos_id
                if "tag" in content[attr]:
                    evc_dict[attr]["tag"] = content[attr]["tag"]
            else:
                evc_dict[attr] = content[attr]

        try:
            kytos_evc_url = os.environ.get(
                "KYTOS_EVC_URL", settings.KYTOS_EVC_URL
            )
            response = requests.post(
                    kytos_evc_url,
                    json=evc_dict,
                    timeout=30)
            assert response.status_code == 201, response.text
        except requests.exceptions.Timeout as exc:
            log.warn("EVC creation failed timout on Kytos: %s", exc)
            raise HTTPException(
                    400,
                    detail=f"Request to Kytos timeout: {exc}"
                ) from exc
        except AssertionError as exc:
            log.warn("EVC creation failed on Kytos: %s", exc)
            raise HTTPException(
                    400,
                    detail=f"Request to Kytos failed: {exc}"
                ) from exc
        except Exception as exc:
            log.warn("EVC creation failed on Kytos request: %s", exc)
            raise HTTPException(
                    400,
                    detail=f"Request to Kytos failed: {exc}"
                ) from exc

        return JSONResponse(response.json(), 200)