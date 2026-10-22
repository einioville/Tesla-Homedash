cmake_minimum_required(VERSION 3.16)

project(frontend_v2 VERSION 0.1 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Without this, AUTOMOC ignores .hh headers (the project's header extension),
# so Q_OBJECT classes in core/*.hh never get moc'd → link errors on the
# meta-object symbols. CMP0100 (CMake 3.18+) opts .hh/.h++ into AUTOMOC.
cmake_policy(SET CMP0100 NEW)

find_package(Qt6 REQUIRED COMPONENTS Quick Network Concurrent Svg Location Positioning QuickControls2 Core5Compat Graphs LabsFolderListModel VirtualKeyboard ShaderTools CanvasPainter)

# 6.12: Canvas2D (Qt Canvas Painter), which no item draws with at present — kept, with the
# OpenGL 3 context AppConfig asks for it, until that is decided (#83).
qt_standard_project_setup(REQUIRES 6.12)

# The C++ data/transport layer in core/ uses Q_OBJECT / Q_PROPERTY — needs AUTOMOC.
set(CMAKE_AUTOMOC ON)

# Some sources contain UTF-8 literals (e.g. the °C unit in the generated Tesla
# code); make MSVC read sources as UTF-8 rather than the system code page.
add_compile_options($<$<CXX_COMPILER_ID:MSVC>:/utf-8>)

# --- Compiler cache (sccache / ccache) -------------------------------------
# Reuse compiled objects across builds AND across git worktrees, so a fresh
# worktree's "clean" rebuild is mostly cache hits. Auto-enabled when sccache or
# ccache is on PATH; a plain no-op otherwise. On MSVC the cache can only reuse an
# object when its debug info is embedded (/Z7) rather than written to a shared
# .pdb (/Zi), so rewrite the default debug flags accordingly.
find_program(COMPILER_CACHE NAMES sccache ccache)
if(COMPILER_CACHE)
    set(CMAKE_CXX_COMPILER_LAUNCHER "${COMPILER_CACHE}")
    set(CMAKE_C_COMPILER_LAUNCHER "${COMPILER_CACHE}")
    if(MSVC)
        foreach(cfg DEBUG RELWITHDEBINFO)
            string(REPLACE "/Zi" "/Z7" CMAKE_CXX_FLAGS_${cfg} "${CMAKE_CXX_FLAGS_${cfg}}")
            string(REPLACE "/ZI" "/Z7" CMAKE_CXX_FLAGS_${cfg} "${CMAKE_CXX_FLAGS_${cfg}}")
        endforeach()
    endif()
    message(STATUS "Compiler cache enabled: ${COMPILER_CACHE}")
endif()

qt_add_executable(appfrontend_v2
    main.cpp
    core/protocol.hh
    core/seriesbounds.hh
    core/graphseries.hh
    core/graphseries.cpp
    core/logger.hh
    core/logger.cpp
    core/serverclient.hh
    core/serverclient.cpp
    core/scram.hh
    core/scram.cpp
    core/credentialstore.hh
    core/credentialstore.cpp
    core/paireddisplays.hh
    core/paireddisplays.cpp
    core/appconfig.hh
    core/appconfig.cpp
    core/dotenv.hh
    core/dotenv.cpp
    core/settings.hh
    core/settings.cpp
    core/idlewatcher.hh
    core/idlewatcher.cpp
    core/screenpower.hh
    core/screenpower.cpp
    core/connectionprobe.hh
    core/connectionprobe.cpp
    core/screensaverphotos.hh
    core/screensaverphotos.cpp
    core/usbimport.hh
    core/usbimport.cpp
    core/systemstatus.hh
    core/systemstatus.cpp
    core/systemhistory.hh
    core/systemhistory.cpp
    core/logcontrol.hh
    core/logcontrol.cpp
    core/appupdate.hh
    core/appupdate.cpp
    core/spotifyauth.hh
    core/spotifyauth.cpp
    core/spotifydevice.hh
    core/spotifydevice.cpp
    core/tesla/tesladata_gen.hh
    core/tesla/tesladata_gen.cpp
    core/tesla/tesladata.hh
    core/tesla/tesladata.cpp
    core/tesla/teslahistory.hh
    core/tesla/teslahistory.cpp
    core/tesla/teslafieldeditor.hh
    core/tesla/teslafieldeditor.cpp
    core/trip/tripsdata.hh
    core/trip/tripsdata.cpp
    core/trip/currentdrive.hh
    core/trip/currentdrive.cpp
    core/trip/routebands.hh
    core/trip/routebands.cpp
    core/map/placenames.hh
    core/map/placenames.cpp
    core/map/geocoder.hh
    core/map/geocoder.cpp
    core/charging/chargingdata.hh
    core/charging/chargingdata.cpp
    core/media/mediaimagecache.hh
    core/media/mediaimageprovider.hh
    core/media/mediadata.hh
    core/media/mediadata.cpp
    core/weather/weatherdata.hh
    core/weather/weatherdata.cpp
    core/notification/notificationhandler.hh
    core/notification/notificationhandler.cpp
)

# Theme is a QML singleton: the pragma in app/Theme.qml plus this source
# property are both required so the `singleton` line is written to qmldir.
# Must be set before qt_add_qml_module().
set_source_files_properties(app/Theme.qml PROPERTIES QT_QML_SINGLETON_TYPE TRUE)

qt_add_qml_module(appfrontend_v2
    URI frontend_v2
    QML_FILES
        Main.qml
        app/ViewController.qml
        app/Theme.qml
        app/Format.js
        views/DashboardView.qml
        views/HistoryView.qml
        views/MediaView.qml
        views/MapView.qml
        views/TripsView.qml
        views/ChargingView.qml
        views/SettingsView.qml
        views/WeatherView.qml
        items/settings/SettingRow.qml
        items/settings/SettingRules.qml
        items/settings/SettingSwitch.qml
        items/settings/SettingSlider.qml
        items/settings/SettingNumber.qml
        items/settings/SettingAction.qml
        items/settings/SettingText.qml
        items/settings/SettingSelect.qml
        items/settings/SettingsSidebar.qml
        items/settings/SettingsPane.qml
        items/settings/BackendProbeStatus.qml
        items/settings/ScreenPowerStatus.qml
        items/settings/EqualizerPanel.qml
        items/settings/TeslaFieldTable.qml
        items/settings/SystemStatusSection.qml
        items/settings/SystemOverviewCard.qml
        items/settings/SystemGraphCard.qml
        items/settings/SystemServiceCard.qml
        items/settings/SystemLogPopup.qml
        items/settings/DebugLogDetails.qml
        items/settings/DebugLogPopup.qml
        items/settings/LogClearPopup.qml
        items/settings/UpdatePanel.qml
        items/settings/UpdateBanner.qml
        items/settings/SettingDetails.qml
        items/settings/SpotifyAuthDetails.qml
        items/settings/SpotifyDeviceDetails.qml
        items/settings/ScreensaverPhotosDetails.qml
        items/settings/SettingsIssues.qml
        items/settings/SettingsIssuesPopup.qml
        items/settings/SettingSpotlight.qml
        items/settings/SpotifyAuthPopup.qml
        items/settings/SpotifyDevicePopup.qml
        items/settings/UsbImportPopup.qml
        items/settings/SpotifyButton.qml
        items/settings/DialogButton.qml
        items/settings/HomeLocationDetails.qml
        items/settings/HomeLocationPopup.qml
        items/settings/ModalDialog.qml
        items/settings/SpotifyAuthAlert.qml
        items/settings/BackendLoginPrompt.qml
        items/settings/BackendLoginDetails.qml
        items/settings/PairedDisplaysPanel.qml
        items/trip/TripMap.qml
        items/trip/TripComboBox.qml
        items/trip/WeekSelector.qml
        items/trip/TripSelector.qml
        items/trip/TripMarker.qml
        items/trip/TripStatCard.qml
        items/trip/TripStatsGrid.qml
        items/trip/TripGraphCard.qml
        items/charging/ChargingGraphCard.qml
        items/charging/ChargingStatsGrid.qml
        items/charging/ChargingLiveCard.qml
        items/history/PropertySelector.qml
        items/history/RangeSelector.qml
        items/history/DateTimePicker.qml
        items/history/HistoryGraph.qml
        items/history/GraphPrewarm.qml
        items/luna/Luna.qml
        items/util/HomeIndicator.qml
        items/util/TextButton.qml
        items/util/MarqueeText.qml
        items/util/Card.qml
        items/util/GlowBorder.qml
        items/util/TintedIcon.qml
        items/util/GlowIcon.qml
        items/util/HoldRepeatArea.qml
        items/util/WheelStepArea.qml
        items/util/ReleaseVelocity.qml
        items/util/ToggleSwitch.qml
        items/util/Reveal.qml
        items/util/ElasticFlickable.qml
        items/util/RoundedImage.qml
        items/util/GlassPanel.qml
        items/util/FrostLayer.qml
        items/util/NotificationLayer.qml
        items/util/ScreenSaver.qml
        items/util/NightSchedule.qml
        items/tesla/DataEntry.qml
        items/tesla/DataEntryList.qml
        items/tesla/TemperatureCard.qml
        items/tesla/ClimateStarter.qml
        items/tesla/ClimateWave.qml
        items/tesla/SeatWidget.qml
        items/tesla/SteeringWidget.qml
        items/tesla/ClimateCard.qml
        items/tesla/TeslaMap.qml
        items/tesla/PlaceLabels.qml
        items/tesla/HomeMarker.qml
        items/tesla/BasemapPlugin.qml
        items/tesla/BasemapSwitch.qml
        items/tesla/MapCoverage.js
        items/tesla/MapLayerMenu.qml
        items/tesla/MapLiveStats.qml
        items/tesla/MapZoomButtons.qml
        items/tesla/MapTouchReveal.qml
        items/tesla/SpeedRoute.qml
        items/tesla/GeoFrame.qml
        items/tesla/MapCameraWatch.qml
        items/tesla/RoadCameras.qml
        items/tesla/RoadCameraPopup.qml
        items/tesla/RoadCameraStations.qml
        items/media/MediaPlayerCard.qml
        items/media/MediaBackdrop.qml
        items/media/MediaSpectrum.qml
        items/media/MediaCover.qml
        items/media/MediaTransport.qml
        items/media/MediaSeekBar.qml
        items/weather/MainWeather.qml
        items/weather/WeatherUtil.js
        items/weather/WeatherWindArrow.qml
        items/weather/WeatherRadarMap.qml
        items/weather/RadarLayer.qml
        items/weather/WarningAreas.qml
        items/weather/WarningLegend.qml
        items/weather/WeatherRadarControls.qml
        items/weather/WeatherSunArc.qml
        items/weather/WeatherMoon.qml
        items/weather/WeatherChart.qml
        items/weather/WeatherHourlyCard.qml
        items/weather/WeatherDashboard.qml
        items/weather/WeatherWarningsPopup.qml
)

set_target_properties(appfrontend_v2 PROPERTIES WIN32_EXECUTABLE TRUE)

# Includes resolve as "core/..." from main.cpp and as siblings within core/.
target_include_directories(appfrontend_v2 PRIVATE ${CMAKE_CURRENT_SOURCE_DIR})

# Stamp the commit this binary was BUILT from. The Options view's update card
# otherwise has to report the repository's HEAD as "the running version", which
# stops being true the moment an update checks out a new commit: between the
# checkout and the app restarting, the repo is at the new version and this
# process is still the old one. Resolved at configure time, and the build script
# configures on every run, so it tracks. Empty when git is unavailable, which
# counts as unknown rather than as a mismatch (AppUpdate::restartPending).
set(FRONTEND_V2_BUILD_COMMIT "")
find_package(Git QUIET)
if(Git_FOUND)
    execute_process(
        COMMAND ${GIT_EXECUTABLE} rev-parse HEAD
        WORKING_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR}
        OUTPUT_VARIABLE FRONTEND_V2_BUILD_COMMIT
        OUTPUT_STRIP_TRAILING_WHITESPACE
        ERROR_QUIET)
endif()

# Bake the source directory so dotenv can locate the repo-root .env even when
# Qt Creator builds the exe outside the source tree (shadow build) — the cwd/exe
# walk-up alone never reaches it. Used only to find .env; real environment
# variables still take precedence, so this absolute dev path is harmless where
# the directory does not exist.
target_compile_definitions(appfrontend_v2 PRIVATE
    FRONTEND_V2_SOURCE_DIR="${CMAKE_CURRENT_SOURCE_DIR}")

# Scoped to the ONE file that reads it, not to the target. As a target-wide
# definition it lands on every translation unit's command line, and its value
# changes with every commit — so each in-app update would recompile the entire
# C++ frontend on the Pi even for a one-line QML change, turning a sub-minute
# build into tens of minutes with the backend already running on a freshly
# synced virtualenv.
set_source_files_properties(core/appupdate.cpp PROPERTIES
    COMPILE_DEFINITIONS "FRONTEND_V2_BUILD_COMMIT=\"${FRONTEND_V2_BUILD_COMMIT}\"")

target_link_libraries(appfrontend_v2
    PRIVATE Qt6::Quick Qt6::Network Qt6::Concurrent Qt6::Svg Qt6::Location Qt6::Positioning
            Qt6::QuickControls2 Qt6::Core5Compat Qt6::Graphs Qt6::LabsFolderListModel
            Qt6::VirtualKeyboard Qt6::CanvasPainter
)

# QML live preview (qmlpreview, or the QmlPreview MCP server an agent drives; Qt 6.12+) needs
# the QML debug service, which can load arbitrary QML into the process. So it is an explicit
# opt-in, never tied to Debug — the build scripts' default, and what a manual build on the Pi
# gets — and the scripts pass it on every configure, so it never lingers in the cache.
option(FRONTEND_V2_QML_PREVIEW "Build with QT_QML_DEBUG for QML live preview (development only)" OFF)
if(FRONTEND_V2_QML_PREVIEW)
    target_compile_definitions(appfrontend_v2 PRIVATE QT_QML_DEBUG)
endif()

# Static resources (font + icons) exposed at :/resources/..., so QML references
# qrc:/resources/icons/... and main.cpp loads the application font from there.
# Kept out of the QML module so the prefix stays /resources rather than
# /qt/qml/frontend_v2.
#
# FMI's SmartSymbol icon set (MIT, see its LICENCE.md); the file names are the
# SmartSymbol values.
file(GLOB SMARTSYMBOL_ICONS RELATIVE ${CMAKE_CURRENT_SOURCE_DIR}
    resources/icons/weather/smartsymbol/*.svg)
qt_add_resources(appfrontend_v2 "smartsymbol_icons"
    PREFIX "/"
    FILES ${SMARTSYMBOL_ICONS}
)

qt_add_resources(appfrontend_v2 "app_resources"
    PREFIX "/"
    FILES
        resources/fonts/gothamrnd_medium.otf
        resources/icons/app.svg
        resources/icons/arrow.svg
        resources/icons/arrow_left.svg
        resources/icons/arrow_right.svg
        resources/icons/camera.svg
        resources/icons/check.svg
        resources/icons/charger.svg
        resources/icons/dots.svg
        resources/icons/chart_line.svg
        resources/icons/exclamation.svg
        resources/icons/pulse.svg
        resources/icons/rotate_left.svg
        resources/icons/heating.png
        resources/icons/home.svg
        resources/icons/layers.svg
        resources/icons/link.svg
        resources/icons/location.svg
        resources/icons/media_pause.svg
        resources/icons/media_play.svg
        resources/icons/media_skip_backward.svg
        resources/icons/media_skip_forward.svg
        resources/icons/music.svg
        resources/icons/minus.svg
        resources/icons/pause.svg
        resources/icons/play.svg
        resources/icons/price.svg
        resources/icons/plus.svg
        resources/icons/seat.svg
        resources/icons/settings.svg
        resources/icons/steering.svg
        resources/icons/terminal.svg
        resources/icons/trip.svg
        resources/icons/warning.svg
        resources/icons/xmark.svg
        resources/icons/weather/clouds.svg
        resources/Luna/stationary.png
        resources/Luna/eating_1.png
        resources/Luna/eating_2.png
        resources/Luna/eating_3.png
        resources/Luna/eating_4.png
        resources/Luna/sitting_1.png
        resources/Luna/sleeping_1.png
        resources/Luna/sniffing_1.png
        resources/Luna/sniffing_2.png
        resources/Luna/sniffing_3.png
        resources/Luna/walking_1.png
        resources/Luna/walking_2.png
        resources/Luna/walking_3.png
        resources/Luna/walking_4.png
        resources/Luna/walking_5.png
        config/notifications.json
        config/settings.json
        config/map-providers/satellite
)

# ShaderEffect shaders, compiled to .qsb at build time and served at
# qrc:/resources/shaders/<file>.qsb. Qt Shader Tools needs no box of its own in
# the Qt installer: it comes with Qt Graphs (Graphs → Quick 3D → Shader Tools).
qt_add_shaders(appfrontend_v2 "shaders"
    PREFIX "/"
    FILES
        resources/shaders/climatesurface.frag
        resources/shaders/climatewater.frag
        resources/shaders/climatewave.frag
        resources/shaders/glassfrost.frag
)

# Developer convenience: regenerate the Tesla data layer from the registry.
# The generated files are committed, so a normal build never needs Python.
find_package(Python3 COMPONENTS Interpreter QUIET)
if(Python3_FOUND)
    add_custom_target(regen_tesla_data
        COMMAND ${Python3_EXECUTABLE}
                ${CMAKE_CURRENT_SOURCE_DIR}/core/tesla/generate_tesladata.py
                ${CMAKE_CURRENT_SOURCE_DIR}/core/tesla/tesla_properties.json
                ${CMAKE_CURRENT_SOURCE_DIR}/core/tesla/tesladata_gen.hh
                ${CMAKE_CURRENT_SOURCE_DIR}/core/tesla/tesladata_gen.cpp
        COMMENT "Regenerating Tesla data layer from tesla_properties.json"
        VERBATIM
    )
endif()

install(TARGETS appfrontend_v2
    LIBRARY DESTINATION ${CMAKE_INSTALL_LIBDIR}
    RUNTIME DESTINATION ${CMAKE_INSTALL_BINDIR}
)
