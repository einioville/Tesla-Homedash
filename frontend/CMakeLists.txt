cmake_minimum_required(VERSION 3.16)

project(gui VERSION 1.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

cmake_policy(SET CMP0100 NEW)

set(CMAKE_AUTOMOC ON)
set(CMAKE_AUTORCC ON)
set(CMAKE_AUTOUIC ON)

set(CMAKE_INTERPROCEDURAL_OPTIMIZATION_RELEASE ON)

find_package(Qt6 REQUIRED COMPONENTS Core Gui Widgets Network QuickWidgets Location Positioning Quick Svg Graphs Concurrent)

set(SOURCES
        src/main.cpp
        src/mainwindow.cpp
        src/config/appconfig.cpp
        src/utils/logger.cpp
        src/tesla/widgets/tesladatawidget.cpp
        src/tesla/vehicle.cpp
        resources.qrc
        src/tesla/widgets/dataentrylist/tesladataentrylist.cpp
        src/server_client/serverclient.cpp
        src/tesla/datahandler/tesladatahandler.cpp
        src/tesla/widgets/singletesladataentry.cpp
        src/mediaplayer/widgets/mediaplayercard.cpp
        src/mediaplayer/datahandler/mediaplayerdatahandler.cpp
        src/tesla/widgets/map/teslamap.cpp
        src/weather/datahandler/weatherdatahandler.cpp
        src/weather/widgets/weatherforecastcard.cpp
        src/weather/widgets/mainweather.cpp
        src/weather/widgets/currentweathercard.cpp
        src/weather/datahandler/weatherdatahandler.cpp
        src/tesla/widgets/climate/climatecontrollercard.cpp
        src/tesla/widgets/climate/temperaturecard.cpp
        src/tesla/widgets/climate/teslaclimatestarter.cpp
        src/tesla/widgets/climate/teslaseatwidget.cpp
        src/tesla/widgets/climate/teslasteeringwidget.cpp
)

set(HEADERS
        src/mainwindow.hh
        src/config/appconfig.hh
        src/utils/logger.hh
        src/tesla/widgets/tesladatawidget.hh
        src/tesla/vehicle.hh
        src/tesla/widgets/dataentrylist/tesladataentrylist.hh
        src/server_client/serverclient.hh
        src/tesla/datahandler/tesladatahandler.hh
        src/tesla/widgets/singletesladataentry.hh
        src/mediaplayer/widgets/mediaplayercard.hh
        src/mediaplayer/datahandler/mediaplayerdatahandler.hh
        src/tesla/widgets/map/teslamap.hh
        src/weather/datahandler/weatherdatahandler.hh
        src/weather/widgets/weatherforecastcard.hh
        src/weather/widgets/mainweather.hh
        src/weather/widgets/currentweathercard.hh
        src/weather/datahandler/weatherdatahandler.hh
        src/tesla/widgets/climate/climatecontrollercard.hh
        src/tesla/widgets/climate/temperaturecard.hh
        src/tesla/widgets/climate/teslaclimatestarter.hh
        src/tesla/widgets/climate/teslaseatwidget.hh
        src/tesla/widgets/climate/teslasteeringwidget.hh
)

add_executable(gui ${SOURCES} ${HEADERS})


target_link_libraries(gui PRIVATE
        Qt6::Core
        Qt6::Gui
        Qt6::Widgets
        Qt6::Network
        Qt6::QuickWidgets
        Qt6::Location
        Qt6::Positioning
        Qt6::Quick
        Qt6::Svg
        Qt6::Graphs
        Qt6::Concurrent
)

target_compile_features(gui PRIVATE cxx_std_20)