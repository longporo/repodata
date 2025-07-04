$(document).ready(function() {
    const issueDataPath = 'issues.csv';
    const commitDataPath = 'commits.csv';
    const prDataPath = 'prs.csv';

    // Tooltip setup
    const ganttTooltip = d3.select("#gantt-tooltip");
    const scatterTooltip = d3.select("#scatter-tooltip");
    const barTooltip = d3.select("#bar-tooltip");

    // --- Data Loading and Processing ---
    Promise.all([
        d3.csv(issueDataPath),
        d3.csv(commitDataPath),
        d3.csv(prDataPath)
    ]).then(function([issueData, commitData, prData]) {
        // Basic check if data loaded
        if (!issueData || issueData.length === 0) {
            console.warn("Issue data is empty or failed to load.");
            // Optionally display a message to the user in the chart container
            d3.select("#gantt-chart").html("<p class='text-danger text-center'>Could not load issues.csv</p>");
            // return; // Stop if issues are critical
        }
        if (!commitData || commitData.length === 0) {
            console.warn("Commit data is empty or failed to load.");
            d3.select("#scatter-chart").html("<p class='text-danger text-center'>Could not load commits.csv</p>");
            d3.select("#bar-chart").html("<p class='text-danger text-center'>Could not load commits.csv</p>");
            // return; // Stop if commits are critical
        }
        if (!prData || prData.length === 0) {
            console.warn("PR data is empty or failed to load.");
            d3.select("#funnel-chart").html("<p class='text-danger text-center'>Could not load prs.csv</p>");
            return;
        }

        // --- Process Issue Data --- (Handle potential errors)
        const parseTime = d3.timeParse("%Y-%m-%dT%H:%M:%SZ");
        let processedIssues = [];
        if (issueData) {
            processedIssues = issueData.map(d => {
                const created = parseTime(d.created_date);
                let closed = d.closed_date ? parseTime(d.closed_date) : new Date(); // Use current date if not closed
                // Ensure closed date is not before created date
                if (closed && created && closed < created) {
                    closed = created; // Or handle as still open, maybe based on state?
                    // If state is closed but closed date is invalid, maybe default to created + 1 day?
                     if (d.state === 'CLOSED') { closed = d3.timeDay.offset(created, 1); }
                     else { closed = new Date(); }
                }
                return {
                    id: d.issue_id,
                    number: +d.issue_number,
                    title: d.title,
                    state: d.state?.toUpperCase() || 'OPEN', // Default to OPEN if state is missing
                    startDate: created,
                    endDate: closed,
                    contributors: d.contributors ? d.contributors.split(';').filter(c => c.trim() !== '') : [],
                    duration: (created && closed) ? d3.timeDay.count(created, closed) : 0,
                    repoOwner: d.repo_owner,
                    repoName: d.repo_name
                };
            }).filter(d => d.startDate); // Filter out issues with invalid start dates
        }

        // --- Process Commit Data ---
        let processedCommits = [];
        if (commitData) {
            processedCommits = commitData.map(d => {
                const date = parseTime(d.created_date);
                return {
                    sha: d.sha,
                    message: d.message,
                    date: date,
                    filesChanged: +d.number_of_files_updated,
                    diff: +d.diff,
                    author: d.author,
                    weekday: date ? date.getDay() : -1, // 0 = Sunday, 6 = Saturday
                    hour: date ? date.getHours() : -1,
                    month: date ? date.getMonth() : -1, // 0 = January, 11 = December
                    year: date ? date.getFullYear() : -1,
                    repoOwner: d.repo_owner,
                    repoName: d.repo_name
                };
            }).filter(d => d.date && d.weekday !== -1 && d.hour !== -1); // Filter out commits with invalid dates
        }

        // Populate month filters
        populateMonthFilters(processedCommits);

        // --- Initial Chart Renders ---
        if (processedIssues.length > 0) renderGanttChart(processedIssues);
        if (processedCommits.length > 0) {
            renderScatterChart(processedCommits);
            renderBarChart(processedCommits);
        }

        // --- Event Listeners for Filters ---
        // Gantt Filters
        $('#gantt-filter-apply').on('click', () => {
            if (processedIssues.length > 0) renderGanttChart(processedIssues);
        });

        // Scatter Filter
        $('#scatter-month-filter').on('change', () => {
             if (processedCommits.length > 0) renderScatterChart(processedCommits);
        });

        // Bar Chart Filters
        $('#bar-metric-select, #bar-month-filter').on('change', () => {
             if (processedCommits.length > 0) renderBarChart(processedCommits);
        });

        // --- Funnel Chart Aggregation and Rendering ---
        if (prData && prData.length > 0) {
            // Aggregation logic
            const funnelStages = [
                { stage: 'Created', count: 0, avgTimeSec: null },
                { stage: 'Reviewed', count: 0, avgTimeSec: null },
                { stage: 'Approved', count: 0, avgTimeSec: null },
                { stage: 'Merged', count: 0, avgTimeSec: null }
            ];
            funnelStages[0].count = prData.length;
            const reviewed = prData.filter(d => d.time_to_first_review_sec && d.time_to_first_review_sec !== '');
            funnelStages[1].count = reviewed.length;
            funnelStages[1].avgTimeSec = reviewed.length > 0 ? d3.mean(reviewed, d => +d.time_to_first_review_sec) : null;
            const approved = prData.filter(d => d.time_to_approval_sec && d.time_to_approval_sec !== '');
            funnelStages[2].count = approved.length;
            funnelStages[2].avgTimeSec = approved.length > 0 ? d3.mean(approved, d => +d.time_to_approval_sec) : null;
            const merged = prData.filter(d => d.was_merged === '1' || d.was_merged === 'true' || d.was_merged === 1);
            funnelStages[3].count = merged.length;
            funnelStages[3].avgTimeSec = merged.length > 0 ? d3.mean(merged, d => +d.time_to_merge_sec) : null;

            renderFunnelChart(funnelStages);
        }

    }).catch(error => {
        console.error('Error loading or processing CSV data:', error);
        // Display error message to the user
         d3.select("#gantt-chart").html("<p class='text-danger text-center'>Error loading data. Check console.</p>");
         d3.select("#scatter-chart").html("<p class='text-danger text-center'>Error loading data. Check console.</p>");
         d3.select("#bar-chart").html("<p class='text-danger text-center'>Error loading data. Check console.</p>");
    });

    // --- Populate Month Filters --- (Helper function)
    function populateMonthFilters(commitData) {
        const months = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
        const availableMonths = [...new Set(commitData.map(d => `${d.year}-${String(d.month + 1).padStart(2, '0')}`))] // Get unique YYYY-MM
                              .sort()
                              .map(ym => {
                                  const [year, month] = ym.split('-');
                                  return { value: ym, text: `${months[parseInt(month) - 1]} ${year}` };
                              });

        const scatterSelect = $('#scatter-month-filter');
        const barSelect = $('#bar-month-filter');
        availableMonths.forEach(m => {
            scatterSelect.append($('<option></option>').attr('value', m.value).text(m.text));
            barSelect.append($('<option></option>').attr('value', m.value).text(m.text));
        });
    }

    // --- Gantt Chart Rendering ---
    function renderGanttChart(data) {
        const container = $("#gantt-chart");
        container.empty(); // Clear previous chart

        // Get filter values
        const developerFilter = $('#gantt-developer-filter').val().toLowerCase();
        const taskFilter = $('#gantt-task-filter').val().toLowerCase();
        const startDateFilter = $('#gantt-start-date').val() ? new Date($('#gantt-start-date').val()) : null;
        const endDateFilter = $('#gantt-end-date').val() ? new Date($('#gantt-end-date').val()) : null;

        // Filter data
        const filteredData = data.filter(d => {
            const devMatch = !developerFilter || d.contributors.some(c => c.toLowerCase().includes(developerFilter));
            const taskMatch = !taskFilter || d.title.toLowerCase().includes(taskFilter);
            const startMatch = !startDateFilter || d.startDate >= startDateFilter;
            const endMatch = !endDateFilter || d.startDate <= endDateFilter;
            return devMatch && taskMatch && startMatch && endMatch;
        });

        if (filteredData.length === 0) {
             container.html("<p class='text-info text-center'>No matching issues found for the selected filters.</p>");
             return;
        }

        // Sort data for better y-axis ordering (e.g., by start date)
        filteredData.sort((a, b) => a.startDate - b.startDate);

        const margin = { top: 30, right: 30, bottom: 70, left: 150 }; // Increased bottom/left margin for labels
        const width = container.width() - margin.left - margin.right;
        const height = Math.max(400, filteredData.length * 25); // Dynamic height based on number of tasks

        const svg = d3.select("#gantt-chart")
            .append("svg")
            .attr("width", width + margin.left + margin.right)
            .attr("height", height + margin.top + margin.bottom)
            .append("g")
            .attr("transform", `translate(${margin.left},${margin.top})`);

        // Scales
        const timeScale = d3.scaleTime()
            .domain([d3.min(filteredData, d => d.startDate), d3.max(filteredData, d => d.endDate)])
            .range([0, width])
            .nice(); // Adjust domain slightly for better axis labels

        const yScale = d3.scaleBand()
            .domain(filteredData.map(d => `Issue ${d.number}`)) // Use issue number for y-axis
            .range([0, height])
            .padding(0.2);

        // Axes
        const xAxis = d3.axisBottom(timeScale).ticks(d3.timeMonth.every(1)).tickFormat(d3.timeFormat("%Y-%m-%d"));
        const yAxis = d3.axisLeft(yScale);

        svg.append("g")
            .attr("class", "x axis")
            .attr("transform", `translate(0,${height})`)
            .call(xAxis)
            .selectAll("text")
            .style("text-anchor", "end")
            .attr("dx", "-.8em")
            .attr("dy", ".15em")
            .attr("transform", "rotate(-45)");

        svg.append("g")
            .attr("class", "y axis")
            .call(yAxis);

        // Gantt Bars
        svg.selectAll(".gantt-rect")
            .data(filteredData)
            .enter()
            .append("rect")
            .attr("class", d => `gantt-rect state-${d.state.toLowerCase()}`)
            .attr("x", d => timeScale(d.startDate))
            .attr("y", d => yScale(`Issue ${d.number}`))
            .attr("width", d => Math.max(1, timeScale(d.endDate) - timeScale(d.startDate))) // Ensure width is at least 1px
            .attr("height", yScale.bandwidth())
            .on("click", function(event, d) {
                if (d.number) {
                    const issueUrl = `https://github.com/${d.repoOwner}/${d.repoName}/issues/${d.number}`;
                    window.open(issueUrl, '_blank');
                } else {
                    console.error("Issue number not found for this task:", d);
                }
            })
            .on("mouseover", function(event, d) {
                ganttTooltip.transition().duration(200).style("opacity", .9);
                ganttTooltip.html(
                    `<strong>Task:</strong> ${d.title}<br/>` +
                    `<strong>Issue #:</strong> ${d.number}<br/>` +
                    `<strong>State:</strong> ${d.state}<br/>` +
                    `<strong>Start:</strong> ${d3.timeFormat("%Y-%m-%d")(d.startDate)}<br/>` +
                    `<strong>End:</strong> ${d3.timeFormat("%Y-%m-%d")(d.endDate)}<br/>` +
                    `<strong>Contributors:</strong> ${d.contributors.join(', ') || 'N/A'}`
                )
                .style("left", (event.pageX + 5) + "px")
                .style("top", (event.pageY - 28) + "px");
            })
            .on("mouseout", function(d) {
                ganttTooltip.transition().duration(500).style("opacity", 0);
            });
    }

    // --- Scatter Chart Rendering ---
    function renderScatterChart(data) {
        const container = $("#scatter-chart");
        container.empty();

        // Filter data
        const monthFilter = $('#scatter-month-filter').val();
        const filteredData = data.filter(d => {
            if (monthFilter === 'all') return true;
            const [year, month] = monthFilter.split('-').map(Number);
            return d.year === year && d.month === month - 1;
        });

         if (filteredData.length === 0) {
             container.html("<p class='text-info text-center'>No matching commits found for the selected filters.</p>");
             return;
        }

        const margin = { top: 30, right: 30, bottom: 50, left: 60 };
        const width = container.width() - margin.left - margin.right;
        const height = 400; // Fixed height for 24 hours

        const svg = d3.select("#scatter-chart")
            .append("svg")
            .attr("width", width + margin.left + margin.right)
            .attr("height", height + margin.top + margin.bottom)
            .append("g")
            .attr("transform", `translate(${margin.left},${margin.top})`);

        // Scales
        const xScale = d3.scaleBand()
            .domain(['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']) // Weekdays
            .range([0, width])
            .padding(0.1);

        const yScale = d3.scaleLinear()
            .domain([0, 24]) // 24 hours
            .range([height, 0]); // Inverted for SVG coordinate system

        // Axes
        const xAxis = d3.axisBottom(xScale);
        const yAxis = d3.axisLeft(yScale).ticks(12).tickFormat(d => `${d}:00`);

        svg.append("g")
            .attr("class", "x axis")
            .attr("transform", `translate(0,${height})`)
            .call(xAxis);

        svg.append("g")
            .attr("class", "y axis")
            .call(yAxis);

        // Axis Labels
        svg.append("text")
            .attr("class", "scatter-axis-label")
            .attr("transform", `translate(${width / 2},${height + margin.bottom - 10})`)
            .style("text-anchor", "middle")
            .text("Day of Week");

        svg.append("text")
            .attr("class", "scatter-axis-label")
            .attr("transform", "rotate(-90)")
            .attr("y", 0 - margin.left)
            .attr("x", 0 - (height / 2))
            .attr("dy", "1em")
            .style("text-anchor", "middle")
            .text("Time of Day (Hour)");

        // Scatter Dots
        const weekdays = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
        svg.selectAll(".scatter-dot")
            .data(filteredData)
            .enter()
            .append("circle")
            .attr("class", "scatter-dot")
            .attr("cx", d => xScale(weekdays[d.weekday]) + xScale.bandwidth() / 2) // Center dot in band
            .attr("cy", d => yScale(d.hour + Math.random())) // Add slight jitter to hour
            .attr("r", 5)
             .on("mouseover", function(event, d) {
                scatterTooltip.transition().duration(200).style("opacity", .9);
                scatterTooltip.html(
                    `<strong>Author:</strong> ${d.author}<br/>` +
                    `<strong>Date:</strong> ${d3.timeFormat("%Y-%m-%d %H:%M")(d.date)}<br/>` +
                    `<strong>Message:</strong> ${d.message}`
                )
                .style("left", (event.pageX + 5) + "px")
                .style("top", (event.pageY - 28) + "px");
            })
            .on("mouseout", function(d) {
                scatterTooltip.transition().duration(500).style("opacity", 0);
            })
            .on("click", function(event, d) {
                if (d.sha) {
                    const commitUrl = `https://github.com/${d.repoOwner}/${d.repoName}/commit/${d.sha}`;
                    window.open(commitUrl, '_blank'); // Open in a new tab
                } else {
                    console.error("Commit SHA not found for this point. Data:", d);
                    alert("Commit details are not available for this point.");
                }
            });
    }

    // --- Bar Chart Rendering ---
    function renderBarChart(data) {
        const container = $("#bar-chart");
        container.empty();

        // Filter data
        const monthFilter = $('#bar-month-filter').val();
        const filteredData = data.filter(d => {
            if (monthFilter === 'all') return true;
            const [year, month] = monthFilter.split('-').map(Number);
            return d.year === year && d.month === month - 1;
        });

        if (filteredData.length === 0) {
             container.html("<p class='text-info text-center'>No matching commits found for the selected filters.</p>");
             return;
        }

        // Aggregate data
        const metric = $('#bar-metric-select').val(); // 'commits' or 'lines'
        const aggregatedData = d3.rollup(filteredData,
            v => metric === 'commits' ? v.length : d3.sum(v, d => d.diff),
            d => d.author
        );

        const chartData = Array.from(aggregatedData, ([author, value]) => ({ author, value }))
                             .sort((a, b) => b.value - a.value); // Sort descending

        const margin = { top: 30, right: 30, bottom: 100, left: 60 }; // Increased bottom margin for rotated labels
        const width = container.width() - margin.left - margin.right;
        const height = 400;

        const svg = d3.select("#bar-chart")
            .append("svg")
            .attr("width", width + margin.left + margin.right)
            .attr("height", height + margin.top + margin.bottom)
            .append("g")
            .attr("transform", `translate(${margin.left},${margin.top})`);

        // Scales
        const xScale = d3.scaleBand()
            .domain(chartData.map(d => d.author))
            .range([0, width])
            .padding(0.2);

        const yScale = d3.scaleLinear()
            .domain([0, d3.max(chartData, d => d.value)])
            .range([height, 0])
            .nice(); // Make the top end at a nice value

        // Axes
        const xAxis = d3.axisBottom(xScale);
        const yAxis = d3.axisLeft(yScale);

        svg.append("g")
            .attr("class", "x axis")
            .attr("transform", `translate(0,${height})`)
            .call(xAxis)
            .selectAll("text") // Rotate labels to prevent overlap
                .style("text-anchor", "end")
                .attr("dx", "-.8em")
                .attr("dy", ".15em")
                .attr("transform", "rotate(-45)");

        svg.append("g")
            .attr("class", "y axis")
            .call(yAxis);

        // Axis Labels
        svg.append("text")
            .attr("class", "bar-axis-label")
            .attr("transform", `translate(${width / 2},${height + margin.bottom - 10})`)
            .style("text-anchor", "middle")
            .text("Author");

        svg.append("text")
            .attr("class", "bar-axis-label")
            .attr("transform", "rotate(-90)")
            .attr("y", 0 - margin.left)
            .attr("x", 0 - (height / 2))
            .attr("dy", "1em")
            .style("text-anchor", "middle")
            .text(metric === 'commits' ? 'Number of Commits' : 'Lines Changed');

        // Bars
        svg.selectAll(".bar-rect")
            .data(chartData)
            .enter()
            .append("rect")
            .attr("class", "bar-rect")
            .attr("x", d => xScale(d.author))
            .attr("y", d => yScale(d.value))
            .attr("width", xScale.bandwidth())
            .attr("height", d => height - yScale(d.value))
            .on("mouseover", function(event, d) {
                barTooltip.transition().duration(200).style("opacity", .9);
                barTooltip.html(
                    `<strong>Author:</strong> ${d.author}<br/>` +
                    `<strong>${metric === 'commits' ? 'Commits' : 'Lines Changed'}:</strong> ${d.value.toLocaleString()}`
                 )
                .style("left", (event.pageX + 5) + "px")
                .style("top", (event.pageY - 28) + "px");
            })
            .on("mouseout", function(d) {
                barTooltip.transition().duration(500).style("opacity", 0);
            });
    }

    function renderFunnelChart(funnelStages) {
        const container = d3.select('#funnel-chart');
        container.html('');
        const width = 600, height = 400, stageHeight = 80, margin = 40;
        const svg = container.append('svg')
            .attr('width', width)
            .attr('height', height);
        const maxCount = funnelStages[0].count;
        const widthScale = d3.scaleLinear().domain([0, maxCount]).range([0, width - 2*margin]);
        function formatTime(sec) {
            if (sec == null) return 'N/A';
            sec = +sec;
            if (sec < 60) return `${sec}s`;
            if (sec < 3600) return `${(sec/60).toFixed(1)} min`;
            if (sec < 86400) return `${(sec/3600).toFixed(1)} hr`;
            return `${(sec/86400).toFixed(1)} d`;
        }
        for (let i = 0; i < funnelStages.length; i++) {
            const topWidth = widthScale(funnelStages[i].count);
            const botWidth = i < funnelStages.length-1 ? widthScale(funnelStages[i+1].count) : topWidth;
            const x0 = (width - topWidth) / 2;
            const x1 = (width - botWidth) / 2;
            const y0 = i * stageHeight + margin;
            const y1 = (i+1) * stageHeight + margin;
            const points = [
                [x0, y0],
                [x0+topWidth, y0],
                [x1+botWidth, y1],
                [x1, y1]
            ];
            svg.append('path')
                .attr('d', d3.line()(points.concat([points[0]])))
                .attr('fill', d3.schemeCategory10[i])
                .attr('stroke', '#333')
                .attr('opacity', 0.85)
                .on('mouseover', function() {
                    d3.select(this).attr('opacity', 1);
                })
                .on('mouseout', function() {
                    d3.select(this).attr('opacity', 0.85);
                });
            svg.append('text')
                .attr('x', width/2)
                .attr('y', y0 + stageHeight/2)
                .attr('text-anchor', 'middle')
                .attr('dominant-baseline', 'middle')
                .attr('font-size', 18)
                .attr('fill', '#fff')
                .text(`${funnelStages[i].stage}: ${funnelStages[i].count} PRs` + (funnelStages[i].avgTimeSec != null ? ` | Avg: ${formatTime(funnelStages[i].avgTimeSec)}` : ''));
        }
    }
});