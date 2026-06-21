#include "weatherforecastmodel.hh"

int WeatherForecastModel::rowCount(const QModelIndex &parent) const {
    return parent.isValid() ? 0 : static_cast<int>(m_rows.size());
}

QVariant WeatherForecastModel::data(const QModelIndex &index, int role) const {
    if (!index.isValid() || index.row() < 0 || index.row() >= m_rows.size()) {
        return QVariant();
    }
    const ForecastRow &row = m_rows.at(index.row());
    switch (role) {
        case HourRole:          return row.hour;
        case TemperatureRole:   return row.temperature;
        case WindSpeedRole:     return row.windSpeed;
        case PrecipitationRole: return row.precipitation;
        case CloudCoverRole:    return row.cloudCover;
        default:                return QVariant();
    }
}

QHash<int, QByteArray> WeatherForecastModel::roleNames() const {
    return {
        {HourRole,          "hour"},
        {TemperatureRole,   "temperature"},
        {WindSpeedRole,     "windSpeed"},
        {PrecipitationRole, "precipitation"},
        {CloudCoverRole,    "cloudCover"},
    };
}

void WeatherForecastModel::setRows(const QVector<ForecastRow> &rows) {
    beginResetModel();
    m_rows = rows;
    endResetModel();
}
